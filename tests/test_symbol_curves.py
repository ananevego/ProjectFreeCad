"""Curve orientation and error bounds measured on serialized native NM points."""
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
from src.symbol_converter.curves import render_curve, _legacy_swap
from src.symbol_converter.target import convert_symbol, LossySymbolConversionError
from src.symbol_converter.schemator_format import parse_cds
from src.component_converter import export_bundle, verify_bundle
from test_symbol_converter import library, symbol, pin, legacy

PROJECT = Path(__file__).resolve().parents[1]
FIXTURES = PROJECT/'tests/fixtures'
STROKE = '(stroke (width 0.254) (type default)) (fill (type none))'


def modern_graphic(graphic):
    pins=pin('1',name='~')+pin('2',name='~',at='5.08 0 180')
    pins=pins.replace('input line','passive line')
    return parse_library(library(symbol(body='(symbol "Base_1_1" '+graphic+pins+')')))


def legacy_graphic(graphic):
    return parse_library(legacy(graphic+'\nX ~ 1 -200 0 100 R 40 40 1 1 P\nX ~ 2 200 0 100 L 40 40 1 1 P'))


def circle(center=(0,0),radius=2):
    return f'(circle (center {center[0]} {center[1]}) (radius {radius}) {STROKE})'


def arc(start=(2,0),mid=(0,2),end=(-2,0)):
    return f'(arc (start {start[0]} {start[1]}) (mid {mid[0]} {mid[1]}) (end {end[0]} {end[1]}) {STROKE})'


def distance(point,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    t=max(0,min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/(dx*dx+dy*dy)))
    return math.hypot(point[0]-a[0]-t*dx,point[1]-a[1]-t*dy)


def native_points(result,curve):
    poly=parse_cds(result.cds).components[0].polylines[curve['target_polyline_index']]
    points=[(c.x/1e6,c.y/1e6) for c in poly.corners]
    if poly.closed: points.append(points[0])
    return points


class SymbolCurveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.device=parse_library((FIXTURES/'symbols/Device.kicad_sym').read_text())
        cls.connector=parse_library((FIXTURES/'symbols/Connector.kicad_sym').read_text())
        cls.cache=parse_library((PROJECT/'KiCad/Pickit-cache.lib').read_text())

    def assert_bound(self,result,curve,samples=1500):
        points=native_points(result,curve)
        center,radius=curve['center_mm'],curve['radius_mm']
        start,sweep=curve['start_angle_radians'],curve['sweep_radians']
        tolerance=curve['tolerance_mm']
        edges=list(zip(points,points[1:]))
        # Dense reference probes -> serialized segments.
        for i in range(samples+1):
            angle=start+sweep*i/samples
            point=(center[0]+radius*math.cos(angle),center[1]+radius*math.sin(angle))
            self.assertLessEqual(min(distance(point,a,b) for a,b in edges),tolerance+1e-10)
        # Exact radial extrema of each native chord: probes alone could miss a
        # narrow worst case, so also check its nearest point to the center.
        for a,b in edges:
            radial_min=distance(center,a,b)
            radial_max=max(math.dist(a,center),math.dist(b,center))
            self.assertLessEqual(max(abs(radial_min-radius),abs(radial_max-radius)),tolerance+1e-10)

    def test_full_official_source_libraries_and_new_footprints_unchanged(self):
        provenance=json.loads((FIXTURES/'symbols/provenance.json').read_text())
        for name in ('Device.kicad_sym','Connector.kicad_sym'):
            record=next(r for r in provenance['files'] if r['file']==name)
            data=(FIXTURES/'symbols'/name).read_bytes()
            self.assertEqual(len(data),record['bytes'])
            self.assertEqual(hashlib.sha256(data).hexdigest(),record['sha256'])
        self.assertEqual(len(self.device.symbols),531)
        self.assertEqual(len(self.connector.symbols),397)
        data=json.loads((FIXTURES/'components/curves-provenance.json').read_text())
        for record in data['files']:
            self.assertEqual(hashlib.sha256((FIXTURES/record['file']).read_bytes()).hexdigest(),record['sha256'])

    def test_circle_is_closed_with_straight_nodes_and_no_duplicate_closing_corner(self):
        result=convert_symbol(modern_graphic(circle()),'Base')
        poly=parse_cds(result.cds).components[0].polylines[0]
        self.assertTrue(poly.closed)
        self.assertEqual((poly.corners[0].x,poly.corners[0].y),(2000000,0))
        self.assertTrue(all(c.node==c.style==0 for c in poly.corners))
        self.assertEqual(len({(c.x,c.y) for c in poly.corners}),len(poly.corners))
        self.assertIsNone(poly.pin)

    def test_circle_tolerance_after_nm_quantization_at_large_translated_origin(self):
        for center in ((0,0),(1024.1234567,-1024.7654321)):
            for tolerance in (.01,.002):
                with self.subTest(center=center,tolerance=tolerance):
                    result=convert_symbol(modern_graphic(circle(center,2.3)),'Base',curve_tolerance=tolerance)
                    self.assert_bound(result,result.report['curves'][0])

    def test_modern_semicircle_preserves_y_up_literal_endpoints(self):
        result=convert_symbol(modern_graphic(arc()),'Base')
        curve=result.report['curves'][0];points=native_points(result,curve)
        self.assertEqual(points[0],(2,0));self.assertEqual(points[-1],(-2,0))
        self.assertTrue(all(y>=0 for _,y in points))
        self.assertFalse(curve['closed'])
        self.assertAlmostEqual(curve['sweep_radians'],math.pi)
        self.assert_bound(result,curve)

    def test_modern_clockwise_semicircle_does_not_flip_to_other_side(self):
        result=convert_symbol(modern_graphic(arc(mid=(0,-2))),'Base')
        curve=result.report['curves'][0]
        self.assertTrue(all(y<=0 for _,y in native_points(result,curve)))
        self.assertAlmostEqual(curve['sweep_radians'],-math.pi)
        self.assert_bound(result,curve)

    def test_modern_large_sweeps_follow_midpoint_in_both_directions(self):
        cases=[(arc(start=(2,0),mid=(-2,0),end=(0,-2)),1),
               (arc(start=(2,0),mid=(-2,0),end=(0,2)),-1)]
        for graphic,sign in cases:
            result=convert_symbol(modern_graphic(graphic),'Base',curve_tolerance=.002)
            curve=result.report['curves'][0]
            self.assertAlmostEqual(curve['sweep_radians'],sign*1.5*math.pi)
            self.assert_bound(result,curve)

    def test_tighter_tolerance_adds_segments_and_is_recorded(self):
        loose=convert_symbol(modern_graphic(circle(radius=3)),'Base',curve_tolerance=.02)
        tight=convert_symbol(modern_graphic(circle(radius=3)),'Base',curve_tolerance=.001)
        self.assertGreater(tight.report['curves'][0]['segments'],loose.report['curves'][0]['segments'])
        self.assertEqual(tight.report['conversion_settings']['curve_tolerance_mm'],.001)
        self.assertEqual(tight.report['target']['profile'],'schemator-cds-straight-v1')
        self.assertEqual(tight.report['target']['source_graphics_profile'],'unfilled-curves-v1')

    def test_invalid_tolerances_reject_even_before_linear_generation(self):
        for tolerance in (0,-1,.00001,1.1,math.nan,math.inf,True,'0.01'):
            with self.subTest(tolerance=tolerance),self.assertRaises(SymbolParseError):
                convert_symbol(self.cache,'R',curve_tolerance=tolerance)

    def test_degenerate_collinear_and_coincident_modern_arcs_reject(self):
        for graphic in (arc(mid=(0,0)),arc(end=(2,0)),arc(mid=(2,0)),arc(start=(0,0),mid=(1,0),end=(2,0))):
            with self.assertRaises(SymbolParseError): convert_symbol(modern_graphic(graphic),'Base')

    def test_out_of_range_or_unstable_derived_circle_rejects(self):
        lib=modern_graphic(arc(start=(0,0),mid=(1,.0001),end=(2,0)))
        with self.assertRaises(SymbolParseError): convert_symbol(lib,'Base')
        lib=modern_graphic(circle());g=lib.get_symbol('Base').units[0].graphics[0]
        for radius in (0,-1,math.nan,math.inf,3000):
            g.geometry['radius']=radius
            with self.assertRaises(SymbolParseError): convert_symbol(lib,'Base')

    def test_native_grid_collapse_and_per_curve_complexity_are_explicit(self):
        for radius,tolerance in ((1e-10,.01),(1000,.000011)):
            with self.assertRaises(SymbolParseError):
                convert_symbol(modern_graphic(circle(radius=radius)),'Base',curve_tolerance=tolerance)

    def test_total_body_complexity_limit_prevents_partial_generation(self):
        with patch('src.symbol_converter.target.MAX_BODY_CORNERS',10):
            with self.assertRaises(SymbolParseError): convert_symbol(modern_graphic(circle()),'Base')

    def test_styled_curve_strokes_are_still_rejected(self):
        for graphic in [circle().replace('type default','type dash'),circle().replace('(type default)','(type default) (color 1 0 0 1)')]:
            with self.assertRaises(SymbolParseError): convert_symbol(modern_graphic(graphic),'Base')

    def test_arc_pin_topology_is_unchanged_and_body_has_no_electrical_nodes(self):
        result=convert_symbol(modern_graphic(arc()),'Base')
        part=parse_cds(result.cds).components[0]
        self.assertTrue(all(c.node==0 for p in part.polylines if not p.pin for c in p.corners))
        self.assertEqual([(p.pin.value,p.corners[-1].x,p.corners[-1].y) for p in part.polylines if p.pin],
                         [('1',-5080000,0),('2',5080000,0)])

    def test_source_model_and_raw_curve_records_are_not_mutated(self):
        source=deepcopy(self.device.get_symbol('L'))
        convert_symbol(self.device,'L')
        self.assertEqual(self.device.get_symbol('L'),source)
        source=deepcopy(self.cache.get_symbol('INDUCTOR'))
        convert_symbol(self.cache,'INDUCTOR')
        self.assertEqual(self.cache.get_symbol('INDUCTOR'),source)

    def test_real_modern_inductor_has_four_correct_right_hand_coils(self):
        result=convert_symbol(self.device,'L')
        self.assertEqual(len(result.report['curves']),4)
        for curve in result.report['curves']:
            points=native_points(result,curve)
            self.assertGreater(max(x for x,_ in points),.6)
            self.assertGreaterEqual(min(x for x,_ in points),-1e-6)
            self.assert_bound(result,curve,samples=400)

    def test_real_circle_and_polarized_arc_controls_have_expected_counts(self):
        for lib,name,count in ((self.device,'C_Polarized_US',1),(self.connector,'TestPoint',1),(self.connector,'Conn_Coaxial',3)):
            result=convert_symbol(lib,name)
            self.assertEqual(result.report['counts']['approximations'],count)
            for curve in result.report['curves']: self.assert_bound(result,curve,samples=400)

    def test_legacy_circle_matches_equivalent_modern_circle_bytes(self):
        old=convert_symbol(legacy_graphic('C 0 0 100 0 1 10 N'),'Test')
        new=convert_symbol(modern_graphic(circle(radius=2.54)),'Base')
        self.assertEqual(parse_cds(old.cds).components[0].polylines[0],parse_cds(new.cds).components[0].polylines[0])

    def test_legacy_semicircle_literal_side_and_endpoint_order(self):
        result=convert_symbol(legacy_graphic('A 0 0 100 0 1800 0 1 10 N 100 0 -100 0'),'Test')
        curve=result.report['curves'][0];points=native_points(result,curve)
        self.assertEqual(points[0],(2.54,0));self.assertEqual(points[-1],(-2.54,0))
        self.assertTrue(all(y<=0 for _,y in points))
        self.assertFalse(curve['legacy_resolution']['endpoints_swapped'])
        self.assert_bound(result,curve)

    def test_legacy_quarter_arc_swap_and_negative_wrap_semantics(self):
        for angles in ('0 900','-3600 4500'):
            result=convert_symbol(legacy_graphic('A 0 0 100 '+angles+' 0 1 10 N 100 0 0 100'),'Test')
            curve=result.report['curves'][0];points=native_points(result,curve)
            self.assertEqual(points[0],(0,2.54));self.assertEqual(points[-1],(2.54,0))
            self.assertTrue(curve['legacy_resolution']['endpoints_swapped'])
            self.assertTrue(all(x>=0 and y>=0 for x,y in points))

    def test_legacy_angle_swap_agrees_with_independent_pinned_trig_algorithm(self):
        # Reference follows the C++ trig/atan2 algorithm, while production uses
        # modular integer algebra. Include the exact 180-degree tie cases.
        def reference(a,b):
            a,b=a%3600,b%3600
            if b-a>=1800: a-=1;b+=1
            a,b=[round(math.degrees(math.atan2(-math.sin(math.radians(v/10)),math.cos(math.radians(v/10))))*10)%3600 for v in (a,b)]
            if b<a:b+=3600
            return b-a>1800
        for a in (-3600,-900,0,513,889,900,1287,1800,2711,4500):
            for b in (-3600,-900,0,513,889,900,1287,1800,2711,4500):
                self.assertEqual(_legacy_swap(a,b),reference(a,b),(a,b))

    def test_legacy_without_endpoints_uses_schematic_iu_rounding(self):
        result=convert_symbol(legacy_graphic('A 0 0 100 0 900 0 1 10 N'),'Test')
        curve=result.report['curves'][0]
        self.assertFalse(curve['legacy_resolution']['explicit_endpoints'])
        self.assertEqual(native_points(result,curve)[0],(0,2.54))
        self.assertEqual(native_points(result,curve)[-1],(2.54,0))

    def test_legacy_full_ring_is_closed_not_a_zero_length_arc(self):
        result=convert_symbol(legacy_graphic('A 0 0 100 0 3600 0 1 10 N 100 0 100 0'),'Test')
        curve=result.report['curves'][0]
        self.assertTrue(curve['closed'])
        self.assertAlmostEqual(curve['sweep_radians'],-math.tau)
        self.assert_bound(result,curve)

    def test_legacy_ambiguous_integer_fields_and_center_endpoints_reject(self):
        for graphic in ('A 0 0 100 0.5 900 0 1 10 N','A 0 0 100 0 900 0 1 10 N 0 0 0 100',
                        'C 0 0 100.5 0 1 10 N','A 0 0 100 2147483648 900 0 1 10 N'):
            with self.assertRaises(SymbolParseError): convert_symbol(legacy_graphic(graphic),'Test')

    def test_legacy_raw_endpoint_disagreement_is_not_hidden_in_tessellation_tolerance(self):
        result=convert_symbol(self.cache,'INDUCTOR')
        curve=result.report['curves'][0]
        self.assertGreater(curve['legacy_resolution']['endpoint_shifts_mm'][1],.025)
        self.assertEqual(curve['max_centerline_error_mm'],.01)
        self.assertIn('source-resolution changes are separate',curve['error_scope'])
        losses=[d for d in result.report['diagnostics'] if d['code']=='SYMBOL_LEGACY_ARC_RESOLVED']
        self.assertEqual(len(losses),4)
        self.assertTrue(all(d['severity']=='loss' for d in losses))
        self.assert_bound(result,curve)

    def test_strict_curve_rejection_keeps_unverified_flags_and_proposal_hash(self):
        with self.assertRaises(LossySymbolConversionError) as raised: convert_symbol(self.device,'L',strict=True)
        report=raised.exception.report
        self.assertFalse(report['target_output_generated'])
        self.assertFalse(report['gui_validated'])
        self.assertFalse(report['target_import_verified'])
        self.assertIn('proposed_artifact_sha256',report)
        self.assertEqual(len(report['curves']),4)

    def test_old_linear_cds_and_reports_are_unchanged(self):
        for name in ('R','C','CONN_01X06'):
            stem=PROJECT/f'output/symbols/{name}_control'
            result=convert_symbol(self.cache,name,project_name=stem.with_suffix('.cds').name)
            old=json.loads(stem.with_suffix('.report.json').read_text())
            self.assertEqual(result.cds.encode('cp1251'),stem.with_suffix('.cds').read_bytes())
            self.assertEqual(json.loads(json.dumps(result.report)),
                             {k:v for k,v in old.items() if k not in ('source','output')})

    def test_cli_curve_tolerance_and_failure_preserve_previous_cds(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);source=root/'curve.kicad_sym';output=root/'curve.cds'
            source.write_text(library(symbol(body='(symbol "Base_1_1" '+circle()+pin('1').replace('input line','passive line')+')')))
            command=[sys.executable,'-B','-m','src.symbol_converter.write',str(source),str(output),'--symbol','Base','--curve-tolerance','0.002']
            result=subprocess.run(command,cwd=PROJECT,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            before=output.read_bytes();report=json.loads(output.with_suffix('.report.json').read_text())
            self.assertEqual(report['curves'][0]['tolerance_mm'],.002)
            result=subprocess.run(command+['--curve-tolerance','nan'],cwd=PROJECT,capture_output=True,text=True)
            self.assertEqual(result.returncode,1)
            self.assertEqual(output.read_bytes(),before)
            result=subprocess.run(command+['--strict'],cwd=PROJECT,capture_output=True,text=True)
            self.assertEqual(result.returncode,2)
            self.assertEqual(output.read_bytes(),before)

    def test_curve_bundle_links_are_verified_and_missing_testpoint_model_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);models=root/'store';model=models/'Inductor_SMD.3dshapes/L_0805_2012Metric.stl'
            model.parent.mkdir(parents=True);model.write_bytes(b'opaque model snapshot')
            output=root/'bundle'
            result=export_bundle(FIXTURES/'components/curves.json',output,stl_root=models,allow_missing_models=True)
            self.assertEqual(result['summary']['generated_components'],3)
            self.assertEqual(result['summary']['complete_chains'],2)
            self.assertEqual(result['summary']['models'],1)
            for entry in result['components']:
                self.assertTrue(entry['source_target_mapping_verified'])
                report=json.loads((output/entry['report']).read_text())
                self.assertTrue(report['symbol_conversion']['curves'])
                self.assertEqual(report['symbol_conversion']['conversion_settings']['curve_tolerance_mm'],.01)
                if entry['id']=='TestPoint':
                    self.assertFalse(entry['chain_complete'])
                    self.assertTrue(entry['model_resolution_diagnostics'])
            relocated=root/'relocated';shutil.copytree(output,relocated);shutil.rmtree(models)
            self.assertEqual(verify_bundle(relocated),result)

    def test_bad_bundle_curve_setting_is_rejected_before_publication(self):
        config=json.loads((FIXTURES/'components/curves.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);path=root/'config.json';output=root/'bundle'
            for value in (.00001,2,True):
                config['symbol_curve_tolerance']=value;path.write_text(json.dumps(config))
                with self.assertRaises(ValueError): export_bundle(path,output)
                self.assertFalse(output.exists())

    def test_saved_real_curve_controls_reproduce_bytes_and_reports(self):
        controls=[(self.device,'L','L_curves'),(self.device,'L_Small','L_Small_curves'),
                  (self.device,'C_Polarized_US','C_Polarized_US_curves'),
                  (self.connector,'TestPoint','TestPoint_curves'),(self.connector,'Conn_Coaxial','Conn_Coaxial_curves'),
                  (self.cache,'CP1','CP1_curves'),(self.cache,'INDUCTOR','INDUCTOR_curves')]
        for lib,name,stem in controls:
            path=PROJECT/'output/symbols'/(stem+'.cds')
            result=convert_symbol(lib,name,project_name=path.name)
            self.assertEqual(result.cds.encode('cp1251'),path.read_bytes())
            report=json.loads(path.with_suffix('.report.json').read_text())
            self.assertEqual(json.loads(json.dumps(result.report)),
                             {k:v for k,v in report.items() if k not in ('source','output')})


if __name__=='__main__':
    unittest.main()
