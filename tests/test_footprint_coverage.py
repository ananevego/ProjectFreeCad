"""Real medium corpus plus numerical technical/contact pad and audit checks."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from src.footprint_converter.parser import parse_sexpr
from src.footprint_converter.pipeline import convert_detailed
from src.footprint_converter.errors import ConversionError, LossyConversionError
from src.footprint_converter.model import ApertureSettings
from src.footprint_converter.batch import run_batch
from src.footprint_converter.audit import audit_batch, read_pads
from test_footprint_converter import source_pad

PROJECT=Path(__file__).resolve().parents[1]
CORPUS=PROJECT/'tests/fixtures/medium'
DEFAULTS=ApertureSettings(.05,0,0)


def footprint_source(body):return f'(footprint "Demo" {body})'


def root(body):return parse_sexpr(footprint_source(body))


class FootprintCoverageTests(unittest.TestCase):
    def test_official_corpus_bytes_git_blobs_license_and_selection_are_fixed(self):
        p=json.loads((CORPUS/'provenance.json').read_text())
        self.assertFalse(p['modified']);self.assertFalse(p['source_tree_metadata']['truncated'])
        self.assertEqual(len(p['files']),120)
        self.assertEqual(sum(r['bytes'] for r in p['files']),908267)
        self.assertEqual(len(p['category_populations']),12)
        self.assertEqual(len(list(CORPUS.rglob('*.kicad_mod'))),120)
        for r in p['files']:
            raw=(CORPUS/r['file']).read_bytes()
            self.assertEqual((len(raw),hashlib.sha256(raw).hexdigest()),(r['bytes'],r['sha256']))
            self.assertEqual(hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest(),r['git_blob_sha1'])
        self.assertEqual(hashlib.sha256((CORPUS/p['license']['file']).read_bytes()).hexdigest(),p['license']['sha256'])

    def test_technical_pad_has_zero_copper_hole_and_exact_source_aperture_size(self):
        tree=root(source_pad(name='',shape='roundrect',size='2 1',at='1 2 90',
            layers='"F.Paste"',extra='(roundrect_rratio 0.25) (solder_paste_margin 0.8) (solder_mask_margin 0.6)'))
        result=convert_detailed(tree,aperture_defaults=ApertureSettings(.9,.9,.2))
        _,pads=read_pads(result.fpl);p=pads[0]
        self.assertEqual((p['name'],p['x'],p['y'],p['hole'],p['angle']),('__TECH_1',1000000,-2000000,0,270))
        self.assertEqual(p['records']['top_pad'],[0,0,0,0,0])
        self.assertEqual(p['records']['bottom_pad'],[0,0,0,0,0])
        self.assertEqual(p['records']['top_paste'],[4,1000000,1000000,1000000,250000])
        self.assertEqual(p['records']['top_mask'],[0,0,0,0,0])
        self.assertEqual(result.report['pad_roles']['technical_carriers'][0]['source']['name'],'')
        self.assertFalse(result.report['pad_roles']['native_netlist_verified'])

    def test_all_explicit_mask_paste_layers_keep_independent_presence(self):
        for layer,key in [('F.Mask','top_mask'),('F.Paste','top_paste'),('B.Mask','bottom_mask'),('B.Paste','bottom_paste')]:
            r=convert_detailed(root(source_pad(name='',layers='"'+layer+'"')),aperture_defaults=DEFAULTS)
            p=read_pads(r.fpl)[1][0]
            self.assertEqual(p['records'][key][0],3)
            self.assertTrue(all(record[0]==0 for other,record in p['records'].items() if other!=key))

    def test_technical_name_collisions_do_not_rename_real_electrical_pin(self):
        r=convert_detailed(root(source_pad(name='',layers='"F.Paste"')+source_pad(name='__TECH_1')),aperture_defaults=DEFAULTS)
        self.assertEqual([p['name'] for p in read_pads(r.fpl)[1]],['__TECH_1_','__TECH_1'])

    def test_generated_carrier_name_cannot_be_truncated_into_existing_name(self):
        body=source_pad(name='',layers='"F.Paste"')
        for n in range(32):body+=source_pad(name='__TECH_1'+'_'*n)
        with self.assertRaisesRegex(ConversionError,'39-character'):convert_detailed(root(body),aperture_defaults=DEFAULTS)

    def test_technical_and_contact_raw_source_trees_remain_unchanged(self):
        tree=root(source_pad(name='',layers='"F.Mask"')+source_pad(kind='connect',layers='"F.Cu" "F.Mask"'))
        before=deepcopy(tree);r=convert_detailed(tree,aperture_defaults=DEFAULTS)
        self.assertEqual(tree,before)
        self.assertEqual((r.report['counts']['technical_carriers'],r.report['counts']['contact_pads']),(1,1))
        from src.footprint_converter.parser import parse_footprint
        from src.component_converter.links import pin_mapping
        from src.component_converter.records import read_fpl_links
        from test_symbol_electrical import modern
        mapping=pin_mapping(modern(('passive',)).get_symbol('Base'),parse_footprint(tree))
        self.assertTrue(mapping['verified']);self.assertEqual(mapping['source_numbers'],['1'])
        native=read_fpl_links(r.fpl)
        self.assertEqual(native['numbers'],['1']);self.assertEqual(native['mechanical_pads'],1)

    def test_contact_uses_surface_geometry_without_connector_attribute_or_paste(self):
        for side in ('F','B'):
            body=source_pad(kind='connect',layers=f'"{side}.Cu" "{side}.Mask"')
            r=convert_detailed(root(body),aperture_defaults=DEFAULTS)
            baseline=convert_detailed(root(body.replace('connect rect','smd rect')),aperture_defaults=DEFAULTS)
            self.assertEqual(r.fpl,baseline.fpl)
            p=read_pads(r.fpl)[1][0]
            self.assertEqual(p['hole'],0)
            self.assertEqual(p['records']['top_paste'],[0,0,0,0,0])
            self.assertEqual(p['records']['bottom_paste'],[0,0,0,0,0])
            self.assertFalse(r.report['pad_roles']['contact_pads'][0]['native_connector_attribute_transferred'])

    def test_invalid_contact_hole_paste_inner_or_double_copper_remain_rejected(self):
        for layers,extra in [('"F.Cu" "F.Mask" "F.Paste"',''),('"F.Cu" "B.Cu"',''),
                             ('"F.Cu" "In1.Cu"',''),('"F.Cu"','(drill 0.4)')]:
            with self.assertRaises(ConversionError):convert_detailed(root(source_pad(kind='connect',layers=layers,extra=extra)))

    def test_unsupported_technical_shapes_holes_layers_and_unnamed_copper_still_reject(self):
        for body in [source_pad(name='',layers='"F.Cu" "F.Paste"'),
                     source_pad(name='',layers='"*.Paste"'),source_pad(name='',layers='"F.SilkS"'),
                     source_pad(name='',layers='"F.Paste"',shape='custom'),
                     source_pad(name='',layers='"F.Paste"',extra='(drill 0.3)')]:
            with self.assertRaises(ConversionError):convert_detailed(root(body))

    def test_strict_reports_losses_and_does_not_silently_drop_technical_pads(self):
        tree=root(source_pad(name='',layers='"F.Paste"')+source_pad(kind='connect',layers='"F.Cu" "F.Mask"'))
        with self.assertRaises(LossyConversionError) as raised:convert_detailed(tree,strict=True,aperture_defaults=DEFAULTS)
        codes={d['code']:d['severity'] for d in raised.exception.report['diagnostics']}
        self.assertEqual(codes['TECHNICAL_PAD_CARRIER'],'loss');self.assertEqual(codes['CONNECT_PAD_TYPE_FLATTENED'],'loss')
        self.assertEqual(raised.exception.report['counts']['written_pins'],2)

    def make_batch(self, root_dir, body=None):
        source=root_dir/'source';source.mkdir()
        (source/'Test.kicad_mod').write_text(footprint_source(body or source_pad()))
        out=root_dir/'batch';run_batch(source,out,stl_root=root_dir/'missing-models',aperture_defaults=DEFAULTS)
        return source,out

    def test_audit_readback_retains_duplicate_numbers_as_ambiguous_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            source,out=self.make_batch(Path(directory),source_pad(name='1')+source_pad(name='1',at='2 0'))
            report=audit_batch(source,out);self.assertEqual(report['summary']['target_records_validated'],1)
            self.assertEqual(report['summary']['ambiguous_number_mapping_items'],1)
            self.assertEqual(report['items'][0]['pad_readback']['duplicate_electrical_numbers'],['1'])

    def test_audit_reports_known_failure_and_malformed_source_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root_dir=Path(directory);source=root_dir/'source';source.mkdir()
            (source/'custom.kicad_mod').write_text(footprint_source(source_pad(shape='custom')))
            (source/'broken.kicad_mod').write_text('(footprint "broken" (pad)')
            out=root_dir/'batch';run_batch(source,out,stl_root=root_dir/'missing-models')
            r=audit_batch(source,out)
            self.assertEqual(r['summary']['failed'],2);self.assertEqual(r['summary']['generated'],0)
            self.assertIn('CUSTOM_PAD_PROFILE_UNSUPPORTED',r['first_failure_categories'])
            self.assertTrue(any('source_inventory_error' in i for i in r['items']))

    def test_audit_rejects_source_artifact_and_report_checksum_corruption(self):
        for target in ('source','output_file','report_file'):
            with tempfile.TemporaryDirectory() as directory:
                source,out=self.make_batch(Path(directory))
                m=json.loads((out/'manifest.json').read_text());e=m['entries'][0]
                path=source/e['source'] if target=='source' else out/e[target]
                path.write_bytes(path.read_bytes()+b' ')
                with self.assertRaisesRegex(ValueError,'checksum'):audit_batch(source,out)

    def test_audit_rejects_traversal_symlink_and_unfinished_manifest(self):
        for mode in ('traversal','symlink','running'):
            with tempfile.TemporaryDirectory() as directory:
                root_dir=Path(directory);source,out=self.make_batch(root_dir)
                p=out/'manifest.json';m=json.loads(p.read_text());e=m['entries'][0]
                if mode=='traversal':e['output_file']='../outside.fpl'
                elif mode=='running':m['status']='running'
                else:
                    path=out/e['output_file'];outside=root_dir/'copy.fpl';shutil.move(path,outside);path.symlink_to(outside)
                p.write_text(json.dumps(m))
                with self.assertRaises(ValueError):audit_batch(source,out)

    def test_audit_rejects_count_status_and_geometry_contradictions_after_rehash(self):
        for mode in ('geometry','count','status'):
            with tempfile.TemporaryDirectory() as directory:
                source,out=self.make_batch(Path(directory));p=out/'manifest.json';m=json.loads(p.read_text());e=m['entries'][0]
                if mode=='geometry':
                    file=out/e['output_file'];raw=file.read_text().replace('-912500','-912510');file.write_text(raw)
                    e['output_sha256']=hashlib.sha256(file.read_bytes()).hexdigest()
                else:
                    file=out/e['report_file'];r=json.loads(file.read_text())
                    if mode=='count':r['counts']['written_pins']=99
                    else:r['status']='failed'
                    file.write_text(json.dumps(r));e['report_sha256']=hashlib.sha256(file.read_bytes()).hexdigest()
                p.write_text(json.dumps(m))
                with self.assertRaises(ValueError):audit_batch(source,out)

    def test_audit_relocates_with_source_and_never_requires_model_store(self):
        with tempfile.TemporaryDirectory() as directory:
            root_dir=Path(directory);source,out=self.make_batch(root_dir)
            first=audit_batch(source,out)
            moved=root_dir/'moved';moved.mkdir();shutil.move(source,moved/'source');shutil.move(out,moved/'batch')
            self.assertEqual(audit_batch(moved/'source',moved/'batch'),first)

    def test_medium_batch_cold_resume_readback_and_failure_totals_are_fixed(self):
        with tempfile.TemporaryDirectory() as directory:
            root_dir=Path(directory);out=root_dir/'batch';models=root_dir/'missing-models'
            m=run_batch(CORPUS,out,stl_root=models,aperture_defaults=DEFAULTS)
            self.assertEqual((m['summary']['generated'],m['summary']['failed']),(110,10))
            r=audit_batch(CORPUS,out,CORPUS/'provenance.json')
            self.assertEqual(r['summary']['target_records_validated'],110)
            self.assertEqual(r['first_failure_categories'],{'DRILL_SLOT_UNSUPPORTED':6,'PAD_OFFSET_UNSUPPORTED':1,'CUSTOM_PAD_NONRECTANGULAR':3})
            self.assertEqual(r['pad_geometry_case_counts'],{'DRILL_SLOT_UNSUPPORTED':22,'PAD_OFFSET_UNSUPPORTED':1,'CUSTOM_PAD_NONRECTANGULAR':3})
            self.assertEqual(r['summary']['unexpected_errors'],0)
            self.assertEqual(sum(r['feature_totals']['pad_kinds'].values()),2557)
            resumed=run_batch(CORPUS,out,stl_root=models,aperture_defaults=DEFAULTS,resume=True)
            self.assertEqual(resumed['summary']['reused'],110)
            self.assertTrue(all(not e['reused'] for e in resumed['entries'] if e['status']=='failed'))

    def test_audit_provenance_detects_wrong_inventory_or_blob_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root_dir=Path(directory);source,out=self.make_batch(root_dir);p=root_dir/'provenance.json'
            raw=(source/'Test.kicad_mod').read_bytes()
            record=dict(file='Test.kicad_mod',bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest(),git_blob_sha1=hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest())
            for records in ([],[dict(record,git_blob_sha1='0'*40)]):
                p.write_text(json.dumps(dict(files=records)))
                with self.assertRaises(ValueError):audit_batch(source,out,p)

    def test_audit_CLI_is_read_only_and_preserves_existing_report_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root_dir=Path(directory);source,out=self.make_batch(root_dir);report=root_dir/'audit.json'
            cmd=[sys.executable,'-B','-m','src.footprint_converter.audit',str(source),str(out),str(report)]
            r=subprocess.run(cmd,cwd=PROJECT,capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
            before=report.read_bytes();(source/'Test.kicad_mod').write_text('modified')
            r=subprocess.run(cmd,cwd=PROJECT,capture_output=True,text=True);self.assertEqual(r.returncode,1,r.stderr)
            self.assertEqual(report.read_bytes(),before)
            cmd[-1]=str(source/'replace.json');r=subprocess.run(cmd,cwd=PROJECT,capture_output=True,text=True)
            self.assertEqual(r.returncode,1,r.stderr);self.assertFalse((source/'replace.json').exists())


if __name__=='__main__':unittest.main()
