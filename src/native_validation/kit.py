"""Build and verify an isolated native-validation kit with existing converters."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

from src.component_converter.bundle import export_bundle, verify_bundle, load_config
from src.footprint_converter.audit import read_pads
from src.footprint_converter.errors import PadGeometryError
from src.footprint_converter.io import validate_output_path
from src.footprint_converter.model import ApertureSettings
from src.footprint_converter.model_matching import DEFAULT_STL_ROOT
from src.footprint_converter.parser import parse_sexpr
from src.footprint_converter.pipeline import convert_detailed
from .portable import FLAGS, digest, json_bytes, load_json, member, verify_kit
from .protocol import protocol, results_template, README


BUNDLES = {'control':(3,3), 'curves':(3,2), 'electrical':(2,2), 'body':(2,2),
           'units':(3,3), 'power':(3,3), 'pins':(5,5), 'common':(3,3)}
FOOTPRINTS = {
    'npth': 'tests/fixtures/MountingHole_3.2mm_M3.kicad_mod',
    'fills': 'tests/fixtures/FilledCircle_Control.kicad_mod',
    'strokes': 'tests/fixtures/strokes/StrokePatterns_Control.kicad_mod',
    'pad-reductions': 'tests/fixtures/pad-geometry/PadGeometry_Control.kicad_mod',
    'technical-contact': 'tests/fixtures/native/TechnicalContact_Control.kicad_mod',
}


def build_kit(project: Path, output: Path, *, stl_root: Path = DEFAULT_STL_ROOT,
              allow_missing_models: bool = False) -> dict:
    project, output, stl_root = Path(project).resolve(), Path(output).resolve(), Path(stl_root).resolve()
    validate_output_path(output, project, stl_root)
    for protected in (project/'src', project/'tests/fixtures', project/'KiCad', stl_root, project/'step_files'):
        if output.is_relative_to(protected.resolve()) or protected.resolve().is_relative_to(output):
            raise ValueError('Native kit cannot overlap source/code/model directories')
    if output.exists() or output.is_symlink(): raise ValueError('Native kit output must be a new directory')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.native-kit-', dir=output.parent) as temporary:
        stage = Path(temporary)/'kit'; stage.mkdir()
        copied = set()
        def source(relative):
            path = member(project, relative)
            if not path.is_file(): raise ValueError('Missing kit source: '+relative)
            target = member(stage, 'source/'+relative)
            if relative not in copied:
                target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(path, target); copied.add(relative)
            return 'source/'+relative
        def snapshot(path):
            path = Path(path).resolve()
            if not path.is_relative_to(project): raise ValueError('Kit source escapes project')
            return source(path.relative_to(project).as_posix())
        bundles, aliases, scenes, catalog = [], {}, [], []
        for name, (expected_total, expected_chains) in BUNDLES.items():
            config_path = project/'tests/fixtures/components'/(name+'.json')
            config, _ = load_config(config_path)
            source('tests/fixtures/components/'+name+'.json')
            destination = stage/'bundles'/name
            m = export_bundle(config_path, destination, stl_root=stl_root,
                allow_missing_models=allow_missing_models or name=='curves')
            if m['summary']['total'] != expected_total or m['summary']['generated_components'] != expected_total:
                raise ValueError('Incomplete native bundle: '+name)
            if not allow_missing_models and m['summary']['complete_chains'] != expected_chains:
                raise ValueError('Missing required native model chains: '+name)
            verify_bundle(destination)
            bundles.append(dict(id=name, path='bundles/'+name, summary=m['summary']))
            for model in m['models']:
                alias = model['import_basename']
                record = dict(import_basename=alias, path='openscad_models/Bundle.3dshapes/'+alias,
                    source_relative=model['source_relative'], bytes=model['bytes'], sha256=model['sha256'])
                folded = alias.casefold()
                if folded in aliases and aliases[folded] != record: raise ValueError('Global native alias collision')
                if folded not in aliases:
                    target = member(stage, record['path']); target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(destination/model['runtime_path'], target)
                    aliases[folded] = record
            for component in m['components']:
                original = component['source']; base = config_path.parent
                snapshot(base/original['symbol_library'])
                library, footprint = original['footprint_identifier'].split(':')
                snapshot(base/config['footprint_libraries'][library]/(footprint+'.kicad_mod'))
                native_fpl = destination/component['footprint']
                name_read, pads = read_pads(native_fpl.read_bytes().decode('cp1251'))
                catalog.append(dict(id=name+'.'+component['id'], kind='component',
                    fpl='bundles/'+name+'/'+component['footprint'], cds='bundles/'+name+'/'+component['symbol'],
                    target_name=name_read, pads=pads, source_pin_numbers=component['pin_mapping']['source_numbers'],
                    pin_mapping=component['pin_mapping'], model_chain_available=component['chain_complete']))
                if component['models']:
                    key = name+'.'+component['id']; code = ['// Library-local preview only; board frame/alignment unverified.']
                    for model in component['models']:
                        t = model['transform']
                        vector = lambda values: '['+','.join(format(v, '.9g') for v in values)+']'
                        code.append('translate('+vector(t['translation'])+') rotate('+vector(t['rotation'])+') scale('+vector(t['scale'])+')')
                        code.append('import("../openscad_models/Bundle.3dshapes/'+model['import_basename']+'");')
                    path = 'scenes/'+key+'.scad'; p = member(stage, path); p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_text('\n'.join(code)+'\n', encoding='utf-8')
                    scenes.append(dict(id=key, path=path, imports=[v['import_basename'] for v in component['models']]))
        footprints = []
        for key, relative in FOOTPRINTS.items():
            src = source(relative); root = parse_sexpr(member(project, relative).read_text())
            result = convert_detailed(root, stl_root=Path(temporary)/'no-standalone-models', aperture_defaults=ApertureSettings(.05,0,0))
            folder = stage/'footprints'/key; folder.mkdir(parents=True)
            (folder/'footprint.fpl').write_bytes(result.fpl.encode('cp1251'))
            (folder/'report.json').write_bytes(json_bytes(result.report))
            entry = dict(id=key, source=src, output='footprints/'+key+'/footprint.fpl', report='footprints/'+key+'/report.json')
            footprints.append(entry)
            name_read,pads = read_pads(result.fpl)
            catalog.append(dict(id=key, kind='standalone_2d', fpl=entry['output'], target_name=name_read, pads=pads,
                diagnostics=result.report['diagnostics'], model_chain_available=False))
        refusals = []
        audit = load_json(project/'output/footprint-pad-geometry-medium.audit.json')
        for item in audit['items']:
            if item['status'] != 'failed': continue
            relative = 'tests/fixtures/medium/'+item['source']; src = source(relative)
            try:
                convert_detailed(parse_sexpr(member(project, relative).read_text()), aperture_defaults=ApertureSettings(.05,0,0))
            except PadGeometryError as error:
                code = error.report['diagnostics'][0]['code']
                if code != item['failure_category']: raise ValueError('Native refusal baseline changed')
                path = 'refusals/'+Path(relative).stem+'.json'
                target = member(stage, path); target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(json_bytes(error.report))
                refusals.append(dict(source=src, report=path, code=code))
            else:
                raise ValueError('Expected native refusal now generates; update the validation profile')
        if len(refusals) != 10: raise ValueError('Expected ten native negative controls')
        for relative in ('tests/fixtures/LICENSE.md', 'tests/fixtures/README.md',
                         'tests/fixtures/symbols/LICENSE.md', 'tests/fixtures/symbols/provenance.json',
                         'tests/fixtures/medium/LICENSE.md', 'tests/fixtures/medium/provenance.json',
                         'tests/fixtures/strokes/README.md', 'tests/fixtures/pad-geometry/README.md',
                         'tests/fixtures/native/README.md'):
            source(relative)
        for p in sorted((project/'tests/fixtures/components').glob('*provenance.json')): snapshot(p)
        (stage/'source-index.json').write_bytes(json_bytes(dict(scope='Selected unchanged source files; provenance may describe a larger corpus', files=sorted(copied))))
        (stage/'expected-catalog.json').write_bytes(json_bytes(dict(schema_version=1, entries=catalog,
            scope='Generated record oracle in NM; native loader/rendering and physical frame remain unverified')))
        (stage/'protocol.json').write_bytes(json_bytes(protocol()))
        (stage/'results-template.json').write_bytes(json_bytes(results_template()))
        (stage/'README.md').write_text(README, encoding='utf-8')
        shutil.copyfile(Path(__file__).with_name('portable.py'), stage/'verify_kit.py')
        models = sorted(aliases.values(), key=lambda v:v['path'])
        summary = dict(bundles=len(bundles), components=sum(b['summary']['total'] for b in bundles),
            generated_components=sum(b['summary']['generated_components'] for b in bundles),
            complete_chains=sum(b['summary']['complete_chains'] for b in bundles),
            models=len(models), footprints=len(footprints), refusals=len(refusals), scenes=len(scenes), manual_checks=len(protocol()['checks']))
        expected_chains = sum(v[1] for v in BUNDLES.values())
        files = [dict(path=p.relative_to(stage).as_posix(), bytes=p.stat().st_size, sha256=digest(p.read_bytes()))
                 for p in sorted(stage.rglob('*')) if p.is_file()]
        manifest = dict(schema_version=1, kind='native_validation_kit',
            targets=dict(freepcb='2.428', schemator='1.429', units='MM'),
            expected_complete_chains=expected_chains, ready_for_3d_checks=summary['complete_chains']==expected_chains,
            **{k:False for k in FLAGS}, bundles=bundles, footprints=footprints, refusals=refusals,
            models=models, scenes=scenes, files=files, summary=summary)
        (stage/'manifest.json').write_bytes(json_bytes(manifest))
        verify_kit(stage)
        if output.exists() or output.is_symlink(): raise ValueError('Output appeared during native kit staging')
        stage.rename(output)
    return verify_kit(output)
