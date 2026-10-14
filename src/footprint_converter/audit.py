"""Read-only source/record coverage audit of a completed footprint batch.

Raw feature inventories include failed items. Generation, exact record checks,
unique number mapping, model availability and native GUI validation stay distinct.
"""
from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
from src.symbol_converter.schemator_format import _tokens

from .parser import parse_sexpr, parse_footprint
from .batch import SUCCESS, summary
from .io import atomic_write, validate_output_path
from .model_matching import DEFAULT_STL_ROOT


def sha(data):return hashlib.sha256(data).hexdigest()


def member(base, relative):
    if not isinstance(relative,str) or not relative or '\\' in relative:
        raise ValueError('Invalid relative audit path')
    path=PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError('Audit path escapes root')
    candidate=base.joinpath(*path.parts)
    if candidate.is_symlink() or not candidate.resolve().is_relative_to(base.resolve()):
        raise ValueError('Audit path is a symlink or escapes root')
    return candidate


def checked_bytes(path, expected):
    raw=path.read_bytes()
    if sha(raw)!=expected:raise ValueError('Audit checksum mismatch: '+path.name)
    return raw


def inventory(root):
    pads=[p for p in root if isinstance(p,list) and p and p[0]=='pad']
    graphics=Counter(p[0] for p in root if isinstance(p,list) and p and p[0].startswith('fp_'))
    def layers(p):return next((v[1:] for v in p if isinstance(v,list) and v and v[0]=='layers'),[])
    def drill(p):
        v=next((v for v in p if isinstance(v,list) and v and v[0]=='drill'),None)
        return 'none' if v is None else 'oval_or_offset' if len(v)!=2 or v[1]=='oval' else 'round'
    return dict(pads=len(pads),pad_kinds=dict(sorted(Counter(p[2] for p in pads).items())),
        pad_shapes=dict(sorted(Counter(p[3] for p in pads).items())),
        drills=dict(sorted(Counter(drill(p) for p in pads).items())),graphics=dict(sorted(graphics.items())),
        unnamed_pads=sum(not p[1] for p in pads),
        technical_only_pads=sum(bool(layers(p)) and not any(v.endswith('.Cu') for v in layers(p)) and p[2]=='smd' for p in pads),
        model_references=sum(isinstance(p,list) and bool(p) and p[0]=='model' for p in root))


def read_pads(text):
    """Independent reader for generated padstacks, including repeated numbers."""
    names=[];declared=[];pads=[];current=None
    fields={'top_pad','bottom_pad','inner_pad','top_mask','bottom_mask','top_paste','bottom_paste'}
    for line in text.splitlines():
        key,sep,value=line.strip().partition(':')
        if not sep or key not in fields|{'name','n_pins','pin'}:continue
        tokens=_tokens(value)
        if key=='name':
            if len(tokens)!=1:raise ValueError('Invalid audit FPL name')
            names.extend(tokens)
        elif key=='n_pins':
            if len(tokens)!=1:raise ValueError('Invalid audit FPL pin count')
            declared.append(int(tokens[0]))
        elif key=='pin':
            if len(tokens)!=6:raise ValueError('Invalid audit FPL pin')
            current=dict(name=tokens[0],hole=int(tokens[1]),x=int(tokens[2]),y=int(tokens[3]),angle=int(tokens[4]),records={})
            pads.append(current)
        else:
            if current is None or key in current['records'] or len(tokens)!=(6 if key=='inner_pad' else 5):
                raise ValueError('Invalid audit FPL pad record')
            numbers=list(map(int,tokens));shape,height,x1,x2,radius=numbers[:5]
            if shape not in {0,1,3,4,5,99} or min(height,x1,x2,radius)<0 or shape==99 and key.endswith('_pad'):
                raise ValueError('Invalid audit FPL pad shape/dimensions')
            if shape not in {0,99} and (not height or not x1+x2 or radius>min(height//2,(x1+x2)//2)):
                raise ValueError('Invalid audit FPL pad bounds')
            current['records'][key]=numbers
    required=fields-{'inner_pad'}
    if len(names)!=1 or declared!=[len(pads)] or any(not required<=set(p['records']) for p in pads):
        raise ValueError('Incomplete audit FPL records')
    return names[0],pads


def verify_pad_identity(fp, name, pads, report):
    if name!=fp.name or len(pads)!=len(fp.pads):raise ValueError('Source/FPL name or pad count mismatch')
    def nm(mm):return round(mm*100000)*10
    electrical=[];technical=0
    shapes={'circle':1,'rect':3,'roundrect':4,'oval':5}
    for i,(source,target) in enumerate(zip(fp.pads,pads)):
        if (target['x'],target['y'],target['hole'],target['angle'])!=(nm(source.x),nm(-source.y),nm(source.drill),-round(source.rotation)%360):
            raise ValueError('Source/FPL pad position, drill or angle mismatch')
        copper={v for v in source.layers if v.endswith('.Cu')}
        if source.kind=='np_thru_hole':copper=set()
        for side,layer in [('top','F.Cu'),('bottom','B.Cu'),('inner','*.Cu')]:
            record=target['records'].get(side+'_pad',[0,0,0,0,0])
            present=layer in copper or '*.Cu' in copper
            if (record[0]!=0)!=present:raise ValueError('Source/FPL copper layers mismatch')
            if present and (record[0],record[1],record[2]+record[3])!=(shapes[source.shape],nm(source.height),2*nm(source.width/2)):
                raise ValueError('Source/FPL copper shape or dimensions mismatch')
        if copper:
            if target['name']!=source.name:raise ValueError('Source/FPL electrical number mismatch')
            electrical.append(source.name)
        elif source.kind=='smd':
            technical+=1
            if source.name and target['name']!=source.name:raise ValueError('Technical pad name mismatch')
            for side,prefix in [('top','F'),('bottom','B')]:
                for aperture in ('mask','paste'):
                    record=target['records'][side+'_'+aperture]
                    present=f'{prefix}.{aperture.title()}' in source.layers
                    if (record[0]!=0)!=present:raise ValueError('Technical aperture layers mismatch')
                    if present and (record[0],record[1],record[2]+record[3])!=(shapes[source.shape],nm(source.height),2*nm(source.width/2)):
                        raise ValueError('Technical aperture dimensions mismatch')
            roles=report.get('pad_roles',{}).get('technical_carriers',[])
            role=next((r for r in roles if r['source_pad_index']==i),None)
            if role is None or role['target_name']!=target['name'] or role['target_copper'] or role['target_hole_size_nm']:
                raise ValueError('Technical report role mismatch')
    duplicate=sorted(n for n,c in Counter(electrical).items() if c>1)
    return dict(source_pad_records=len(pads),electrical_pad_records=len(electrical),technical_carriers=technical,
        duplicate_electrical_numbers=duplicate,unique_number_mapping_possible=not duplicate,
        scope='Pad count, literal electrical labels with multiplicity, copper shape/size/layers, location/drill/angle and technical apertures; GUI/netlist/manufacturing unverified')


def failure_category(message):
    for text,code in [('oval/offset drill','DRILL_OVAL_OR_OFFSET'),('pad shape','PAD_SHAPE_UNSUPPORTED'),
                      ('Non-solid graphic stroke','GRAPHIC_STROKE_UNSUPPORTED'),('invalid pin name','PAD_NAME_UNSUPPORTED'),
                      ('unsupported type','PAD_TYPE_UNSUPPORTED'),('unsupported enabled','PADSTACK_UNSUPPORTED'),
                      ('unsupported chamfer','PAD_CHAMFER_UNSUPPORTED'),('model','MODEL_UNSUPPORTED')]:
        if text in message:return code
    return 'UNCLASSIFIED_FAILURE'


def audit_batch(source, batch, provenance=None):
    source,batch=Path(source).resolve(),Path(batch).resolve()
    raw_manifest=(batch/'manifest.json').read_bytes();m=json.loads(raw_manifest)
    if m.get('kind')!='footprint_batch' or m.get('schema_version')!=1 or m.get('status') not in {'completed','completed_with_errors'}:
        raise ValueError('Audit requires a completed footprint batch')
    entries=m['entries']
    if not entries or len({e['source'] for e in entries})!=len(entries) or m['selected']!=len(entries) or any(e['status'] not in SUCCESS|{'failed','rejected_loss'} for e in entries):
        raise ValueError('Invalid/incomplete audit entries')
    if summary(entries)!=m['summary']:raise ValueError('Batch summary mismatch')
    pinned={};provenance_hash=None
    if provenance is not None:
        raw=Path(provenance).read_bytes();p=json.loads(raw);provenance_hash=sha(raw)
        pinned={record['file']:record for record in p['files']}
        if len(pinned)!=len(p['files']) or set(pinned)!={e['source'] for e in entries}:
            raise ValueError('Provenance and selected batch corpus differ')
    items=[];categories=defaultdict(Counter);failures=Counter();features=defaultdict(Counter)
    for e in sorted(entries,key=lambda e:e['source']):
        data=checked_bytes(member(source,e['source']),e['input_sha256'])
        if pinned:
            r=pinned[e['source']]
            blob=hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()
            if (r['sha256'],r['bytes'],r['git_blob_sha1'])!=(sha(data),len(data),blob):raise ValueError('Pinned source provenance mismatch')
        tree=None;inventory_error=None
        try:
            tree=parse_sexpr(data.decode('utf-8'));raw_features=inventory(tree)
        except (ValueError,IndexError,TypeError) as error:
            if e['status'] in SUCCESS:raise ValueError('Successful source cannot be inventoried') from error
            inventory_error=str(error)
            raw_features=dict(pads=None,pad_kinds={},pad_shapes={},drills={},graphics={},unnamed_pads=None,technical_only_pads=None,model_references=None)
        item=dict(source=e['source'],input_sha256=sha(data),status=e['status'],features=raw_features,target_records_validated=False)
        if inventory_error:item['source_inventory_error']=inventory_error
        for key in ('pad_kinds','pad_shapes','drills','graphics'):features[key].update(raw_features[key])
        category=PurePosixPath(e['source']).parts[0];categories[category][e['status']]+=1
        report_raw=checked_bytes(member(batch,e['report_file']),e['report_sha256']);report=json.loads(report_raw)
        if report['status']!=e['status']:raise ValueError('Report status mismatch')
        if e['status'] in SUCCESS:
            if e['output_current'] is not True:raise ValueError('Successful artifact is not current')
            fpl=checked_bytes(member(batch,e['output_file']),e['output_sha256']).decode(m['options']['encoding'])
            name,pads=read_pads(fpl)
            if (report['counts']['source_pads'],report['counts']['written_pins'])!=(len(pads),len(pads)):
                raise ValueError('Report/source/FPL pad counts mismatch')
            fp=parse_footprint(tree,e['target_name'],curve_tolerance=m['options']['curve_tolerance'])
            item.update(target_records_validated=True,pad_readback=verify_pad_identity(fp,name,pads,report),
                output_sha256=e['output_sha256'],matched_models=report['counts']['matched_models'])
        else:
            if e['output_current'] is not False:raise ValueError('Failed artifact incorrectly marked current')
            item.update(errors=e.get('errors',[]),error_type=e.get('error_type'),unexpected_error=e.get('unexpected_error',False))
            item['failure_category']=failure_category(' '.join(item['errors']));failures[item['failure_category']]+=1
        items.append(item)
    return dict(schema_version=1,kind='footprint_batch_audit',batch_manifest_sha256=sha(raw_manifest),
        source_provenance_sha256=provenance_hash,target_gui_validated=False,model_geometry_validated=False,
        manufacturing_validated=False,native_netlist_verified=False,
        options={k:v for k,v in m['options'].items() if k!='stl_root'},
        summary=dict(total=len(items),generated=m['summary']['generated'],generated_with_loss=m['summary']['generated_with_loss'],
            failed=m['summary']['failed'],rejected_loss=m['summary']['rejected_loss'],generation_percent=m['summary']['generation_percent'],
            target_records_validated=sum(i['target_records_validated'] for i in items),
            ambiguous_number_mapping_items=sum(bool(i.get('pad_readback',{}).get('duplicate_electrical_numbers')) for i in items),
            unexpected_errors=sum(i.get('unexpected_error',False) for i in items)),
        categories={k:dict(sorted(v.items())) for k,v in sorted(categories.items())},
        feature_totals={k:dict(sorted(v.items())) for k,v in sorted(features.items())},
        first_failure_categories=dict(sorted(failures.items())),diagnostic_item_counts=m['summary']['diagnostic_item_counts'],items=items)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path);parser.add_argument('batch',type=Path);parser.add_argument('output',type=Path)
    parser.add_argument('--provenance',type=Path);args=parser.parse_args(argv)
    try:
        validate_output_path(args.output,args.input,DEFAULT_STL_ROOT)
        if args.output.suffix!='.json' or args.output.resolve().is_relative_to(args.input.resolve()) or args.output.resolve().is_relative_to(args.batch.resolve()):
            raise ValueError('Audit JSON must be outside source and batch directories')
        if args.provenance and args.output.resolve()==args.provenance.resolve():raise ValueError('Audit cannot replace provenance')
        result=audit_batch(args.input,args.batch,args.provenance)
        atomic_write(args.output,(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n').encode())
    except (OSError,ValueError,KeyError,TypeError) as error:
        print('Footprint audit failed: '+str(error),file=sys.stderr);return 1
    s=result['summary'];print(f"Audit: {s['generated']}/{s['total']} generated, {s['target_records_validated']} record checks, {s['failed']} failed; native GUI unverified")
    return 0


if __name__=='__main__':raise SystemExit(main())
