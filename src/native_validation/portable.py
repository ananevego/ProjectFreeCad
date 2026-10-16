"""Standalone kit integrity/results checker, copied verbatim into each kit.

Uses only Python's standard library. Integrity and protocol consistency do not
attest that an operator performed GUI actions or that models physically align.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


FLAGS = ('native_import_verified', 'gui_validated', 'native_netlist_verified',
         'manufacturing_validated', 'model_geometry_validated')
RESERVED = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{p}{i}' for p in ('COM', 'LPT') for i in range(1, 10)}


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode('utf-8')


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load_json(path):
    def unique(pairs):
        value = {}
        for k, v in pairs:
            if k in value: raise ValueError('Duplicate JSON key: '+k)
            value[k] = v
        return value
    def invalid(value): raise ValueError('Non-finite JSON: '+value)
    return json.loads(Path(path).read_text(encoding='utf-8-sig'), object_pairs_hook=unique, parse_constant=invalid)


def member(root, relative):
    if not isinstance(relative, str) or not relative or '\\' in relative:
        raise ValueError('Invalid portable path')
    p = PurePosixPath(relative)
    if p.is_absolute() or p.as_posix() != relative:
        raise ValueError('Noncanonical portable path')
    for part in p.parts:
        if (part in {'.', '..'} or part.endswith('.') or
                not re.fullmatch(r'[A-Za-z0-9_.-]+', part) or part.split('.')[0].upper() in RESERVED):
            raise ValueError('Unsafe Windows/portable path: '+relative)
    root = Path(root).resolve()
    candidate = root
    for part in p.parts:
        candidate = candidate/part
        if candidate.is_symlink(): raise ValueError('Symlink in kit path')
    if not candidate.resolve().is_relative_to(root): raise ValueError('Path escapes kit')
    return candidate


def verify_kit(root):
    root = Path(root).resolve()
    m = load_json(root/'manifest.json')
    if m.get('kind') != 'native_validation_kit' or m.get('schema_version') != 1:
        raise ValueError('Invalid native kit manifest')
    if any(m.get(k) is not False for k in FLAGS): raise ValueError('Kit cannot claim native validation')
    if m.get('targets') != {'freepcb': '2.428', 'schemator': '1.429', 'units': 'MM'}:
        raise ValueError('Unexpected native targets')
    indexed = set()
    for r in m['files']:
        folded = r['path'].casefold()
        if folded in indexed or folded == 'manifest.json' or folded.split('/')[0] == 'results':
            raise ValueError('Duplicate/reserved kit index')
        path = member(root, r['path'])
        if not path.is_file() or path.stat().st_size != r['bytes'] or digest(path.read_bytes()) != r['sha256']:
            raise ValueError('Kit checksum mismatch: '+r['path'])
        indexed.add(folded)
    actual = set()
    for path in root.rglob('*'):
        relative = path.relative_to(root).as_posix()
        member(root, relative)
        if path.is_file() and relative.split('/')[0] != 'results':
            if relative.casefold() in actual: raise ValueError('Kit case collision')
            actual.add(relative.casefold())
    if actual != indexed | {'manifest.json'}: raise ValueError('Unindexed/missing kit files')
    def indexed_path(relative):
        if relative.casefold() not in indexed: raise ValueError('Unindexed kit reference')
        return member(root, relative)
    ids = set()
    for b in m['bundles']:
        if b['id'] in ids: raise ValueError('Duplicate bundle id')
        ids.add(b['id'])
        sub = load_json(indexed_path(b['path']+'/manifest.json'))
        if sub['kind'] != 'component_bundle' or any(sub.get(k) for k in ('native_import_verified', 'gui_validated', 'model_geometry_validated')):
            raise ValueError('Invalid bundle scope')
        if sub['summary'] != b['summary']: raise ValueError('Bundle summary mismatch')
    model_aliases = set()
    for model in m['models']:
        alias = model['import_basename'].casefold()
        if alias in model_aliases: raise ValueError('Duplicate model alias')
        model_aliases.add(alias)
        raw = indexed_path(model['path']).read_bytes()
        if digest(raw) != model['sha256'] or len(raw) != model['bytes']:
            raise ValueError('Global model alias mismatch')
    scene_ids = set()
    for scene in m['scenes']:
        key = scene['id']
        if (not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', key)
                or key.endswith('.') or key.casefold() in scene_ids or scene['path'] != 'scenes/'+key+'.scad'):
            raise ValueError('Invalid/duplicate scene identity')
        scene_ids.add(key.casefold())
        indexed_path(scene['path'])
        for alias in scene['imports']:
            if alias.casefold() not in model_aliases: raise ValueError('Unresolved scene model')
    for entry in m['footprints']:
        indexed_path(entry['source']); indexed_path(entry['output']); indexed_path(entry['report'])
    for entry in m['refusals']:
        indexed_path(entry['source'])
        r = load_json(indexed_path(entry['report']))
        if r['status'] != 'failed' or entry['code'] not in {d['code'] for d in r['diagnostics']}:
            raise ValueError('Negative control is not the expected refusal')
    protocol = load_json(indexed_path('protocol.json'))
    checks = protocol['checks']
    if len({c['id'] for c in checks}) != len(checks): raise ValueError('Duplicate protocol check')
    template = load_json(indexed_path('results-template.json'))
    if (template['kind'] != 'native_validation_results' or
            [c['id'] for c in template['checks']] != [c['id'] for c in checks] or
            any(c['status'] != 'not_run' or c['evidence'] for c in template['checks'])):
        raise ValueError('Results template must contain only unexecuted checks')
    totals = dict(bundles=len(m['bundles']), components=sum(b['summary']['total'] for b in m['bundles']),
                  generated_components=sum(b['summary']['generated_components'] for b in m['bundles']),
                  complete_chains=sum(b['summary']['complete_chains'] for b in m['bundles']),
                  models=len(m['models']), footprints=len(m['footprints']), refusals=len(m['refusals']),
                  scenes=len(m['scenes']), manual_checks=len(checks))
    if m['summary'] != totals: raise ValueError('Kit summary mismatch')
    if m['ready_for_3d_checks'] != (totals['complete_chains'] == m['expected_complete_chains']):
        raise ValueError('Kit model readiness mismatch')
    return m


def results_path(root, relative):
    if not isinstance(relative, str) or not relative.startswith('results/'):
        raise ValueError('Observations/evidence must be inside results/')
    return member(root, relative)


def init_results(root, relative):
    root = Path(root).resolve()
    verify_kit(root)
    destination = results_path(root, relative)
    result = deepcopy(load_json(Path(root)/'results-template.json'))
    result['kit_manifest_sha256'] = digest((Path(root)/'manifest.json').read_bytes())
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as file: file.write(json_bytes(result))
    return result


def validate_results(root, relative):
    root = Path(root).resolve()
    verify_kit(root)
    result = load_json(results_path(root, relative))
    protocol = load_json(Path(root)/'protocol.json')
    if (result.get('schema_version') != 1 or result.get('kind') != 'native_validation_results' or
            result.get('kit_manifest_sha256') != digest((Path(root)/'manifest.json').read_bytes())):
        raise ValueError('Results do not identify this exact kit')
    definitions = {c['id']: c for c in protocol['checks']}
    if len(result['checks']) != len(definitions) or {c['id'] for c in result['checks']} != set(definitions):
        raise ValueError('Results check IDs differ from protocol')
    counts = {k: 0 for k in ('passed', 'failed', 'blocked', 'not_run')}
    for c in result['checks']:
        status = c['status']
        if status not in counts: raise ValueError('Invalid observation status')
        counts[status] += 1
        if not isinstance(c['notes'], str) or not isinstance(c['evidence'], list): raise ValueError('Invalid observation')
        if status in {'failed', 'blocked'} and not c['notes'].strip(): raise ValueError('Failure/block needs a reason')
        if status == 'passed':
            application = definitions[c['id']]['application']
            required = definitions[c['id']].get('required_versions',
                {application: {'freepcb':'2.428', 'schemator':'1.429'}.get(application)})
            versions_ok = all(isinstance(result['versions'].get(app), str) and result['versions'][app].strip()
                and (expected is None or result['versions'][app] == expected) for app,expected in required.items())
            if (not isinstance(result.get('operator'), str) or not result['operator'].strip() or not versions_ok
                    or not c['notes'].strip() or not c['evidence']):
                raise ValueError('Passed check requires operator, target version, notes and evidence')
        for e in c['evidence']:
            p = results_path(root, e['path'])
            if not p.is_file() or not p.stat().st_size or digest(p.read_bytes()) != e['sha256']:
                raise ValueError('Observation evidence checksum mismatch')
    return counts


def compile_scenes(root, executable, run_id, selected=None):
    root = Path(root).resolve()
    m = verify_kit(root)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', run_id) or run_id.endswith('.'):
        raise ValueError('Invalid OpenSCAD run id')
    executable = str(Path(executable).resolve(strict=True))
    available = {s['id']: s for s in m['scenes']}
    keys = list(available) if selected is None else list(selected)
    if not keys or len(keys) != len(set(keys)) or any(k not in available for k in keys):
        raise ValueError('Unknown/empty/duplicate scene selection')
    output = results_path(root, 'results/'+run_id)
    output.mkdir(parents=True, exist_ok=False)
    report = dict(kind='openscad_csg_probe', schema_version=1,
        kit_manifest_sha256=digest((Path(root)/'manifest.json').read_bytes()),
        scope='CSG script compilation only; STL geometry, GUI, board export and physical alignment unverified',
        **{k: False for k in FLAGS}, scenes=[])
    try:
        version = subprocess.run([executable, '--version'], capture_output=True, text=True, timeout=20)
        report['version'] = (version.stdout+version.stderr).strip()[:2000]
        if version.returncode: raise ValueError('OpenSCAD version probe failed')
        for key in keys:
            target = output/(key+'.csg')
            try:
                run = subprocess.run([executable, '-o', str(target), str(member(root, available[key]['path']))],
                    capture_output=True, text=True, timeout=30)
                messages = (run.stdout+run.stderr)[-20000:]
                passed = run.returncode == 0 and target.is_file() and target.stat().st_size > 0 and not re.search(r'\b(?:ERROR|WARNING)\b', messages, re.I)
                entry = dict(id=key, status='passed' if passed else 'failed', returncode=run.returncode, messages=messages)
                if target.is_file(): entry.update(output=target.relative_to(root).as_posix(), sha256=digest(target.read_bytes()))
            except subprocess.TimeoutExpired:
                entry = dict(id=key, status='failed', messages='OpenSCAD timed out after 30 seconds')
            report['scenes'].append(entry)
    finally:
        (output/'probe.json').write_bytes(json_bytes(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kit', nargs='?', type=Path, default=Path(__file__).resolve().parent)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--init-results'); group.add_argument('--results'); group.add_argument('--compile-openscad', type=Path)
    parser.add_argument('--run-id', default='openscad-csg')
    parser.add_argument('--scene', action='append')
    args = parser.parse_args(argv)
    try:
        if args.init_results:
            init_results(args.kit, args.init_results); print('Created observations; all checks remain not_run.')
        elif args.results:
            counts = validate_results(args.kit, args.results); print(json.dumps(counts))
            return 2 if counts['failed'] or counts['blocked'] else 0
        elif args.compile_openscad:
            result = compile_scenes(args.kit, args.compile_openscad, args.run_id, args.scene)
            passed = sum(c['status'] == 'passed' for c in result['scenes'])
            print(f'OpenSCAD CSG: {passed}/{len(result["scenes"])}; geometry/alignment and native GUI unverified.')
            return 0 if result['scenes'] and passed == len(result['scenes']) else 2
        else:
            m = verify_kit(args.kit); print(json.dumps(m['summary'])+'; file integrity verified; use --results for recorded observations.')
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print('Native kit check failed: '+str(error), file=sys.stderr); return 1
    return 0


if __name__ == '__main__': raise SystemExit(main())
