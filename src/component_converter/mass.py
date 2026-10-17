"""Export the exact candidates from audited batches as one movable linked library.

Libraries are parsed one at a time. Reports stay on disk; selected existing STL
bytes are stored once per source path, with one shared flat native import folder.
Publication is atomic and existing output is never overwritten.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
import zipfile

from .batch_inventory import inventory_links, load_audited
from .bundle import (Assets, SUCCESS, _convert_item, _portable_path, digest,
                     file_digest, finish_bundle, json_bytes, validate_config,
                     verify_bundle)
from src.footprint_converter.io import validate_output_path
from src.footprint_converter.model_matching import DEFAULT_STL_ROOT


def component_id(source, symbol):
    identity = json.dumps([source, symbol], ensure_ascii=False, separators=(',', ':'))
    stem = re.sub(r'[^A-Za-z0-9_.-]', '_', symbol)[:40].strip('._-')
    return 'co_' + stem + '_' + digest(identity.encode())[:16]


def _sources(root, expected):
    for relative, sha in expected.items():
        if file_digest(_portable_path(root, relative)) != sha:
            raise ValueError('Source changed after audit: ' + relative)


def _profile(sm, fm):
    so, fo = sm['options'], fm['options']
    if (so['strict'] or fo['strict'] or so['default_line_width'] != .254 or so['pin_width'] != .254
            or fo['encoding'] != 'cp1251' or fo['curve_tolerance'] != .01 or fo['fill_tolerance'] != .01
            or fo['model_transform'] is not None or fo['text_variables']):
        raise ValueError('Audited options are outside the linked preview profile')
    config = dict(schema_version=1, aperture_defaults=fo['aperture_defaults'],
                  footprint_description_policy=fo.get('description_policy', 'preserve'))
    for key in ('curve_tolerance', 'fill_tolerance', 'unit_gap', 'no_connect_policy',
                'hidden_pin_policy', 'common_pin_policy', 'pin_name_policy', 'alternate_pin_policy'):
        config['symbol_' + key] = so[key]
    return config


def export_mass(symbol_source, symbol_batch, symbol_audit, footprint_source,
                footprint_batch, footprint_audit, output, *, stl_root=DEFAULT_STL_ROOT,
                progress=None):
    """Revalidate both audited snapshots, convert exact matches and publish NEW output."""
    symbol_source, symbol_batch, symbol_audit, footprint_source, footprint_batch, footprint_audit, output = map(
        Path, (symbol_source, symbol_batch, symbol_audit, footprint_source, footprint_batch, footprint_audit, output))
    stl_root = Path(stl_root).resolve()
    validate_output_path(output, symbol_audit, stl_root)
    if (output.exists() or output.is_symlink() or any(output.resolve().is_relative_to(p.resolve())
            for p in (symbol_source, symbol_batch, footprint_source, footprint_batch))):
        raise ValueError('Mass output must be new and outside source/batch directories')
    # This reads current CDS/FPL/report bytes and verifies the audit/manifest bonds.
    candidates = inventory_links(symbol_batch, symbol_audit, footprint_batch, footprint_audit)
    selected = sorted((i for i in candidates['items'] if i['status'] == 'eligible_for_linked_export'),
                      key=lambda i: (i['source'], i['symbol']))
    if not selected:
        raise ValueError('No audited exact candidates')
    sm, sa, _ = load_audited(symbol_batch, symbol_audit, 'symbol')
    fm, fa, _ = load_audited(footprint_batch, footprint_audit, 'footprint')
    selected_symbols = {i['source'] for i in selected}
    selected_footprints = {i['footprint_source'] for i in selected}
    symbol_hashes = {e['source']: e['input_sha256'] for e in sm['libraries'] if e['source'] in selected_symbols}
    fp_hashes = {e['source']: e['input_sha256'] for e in fm['entries'] if e['source'] in selected_footprints}
    _sources(symbol_source, symbol_hashes)
    _sources(footprint_source, fp_hashes)
    config = _profile(sm, fm)
    evidence = dict(kind='audited_linked_preview_inputs', schema_version=1,
                    symbol_audit_sha256=candidates['symbol_audit_sha256'],
                    footprint_audit_sha256=candidates['footprint_audit_sha256'],
                    symbol_batch_sha256=sa['batch_manifest_sha256'],
                    footprint_batch_sha256=fa['batch_manifest_sha256'],
                    symbol_sources=symbol_hashes, footprint_sources=fp_hashes,
                    profile=config.copy(), allow_missing_models=True,
                    native_netlist_verified=False, target_gui_validated=False,
                    model_alignment_validated=False)
    del sm, sa, fm, fa
    config['footprint_libraries'] = {i['source_footprint_identifier'].split(':')[0]: str(
        (footprint_source / (i['source_footprint_identifier'].split(':')[0] + '.pretty')).resolve()) for i in selected}
    config['components'] = [dict(id=component_id(i['source'], i['symbol']),
                                  symbol_library=i['source'], symbol=i['symbol']) for i in selected]
    validate_config(config)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.linked-preview-', dir=output.parent) as temporary:
        stage = Path(temporary) / 'library'
        stage.mkdir()
        assets, cache, entries = Assets(stage), {}, []
        previous = None
        for n, (candidate, component) in enumerate(zip(selected, config['components']), 1):
            if previous != component['symbol_library']:
                cache.clear()
                previous = component['symbol_library']
            entry = _convert_item(component, config, symbol_source, stage, assets, stl_root, cache, True, False)
            source = entry.get('source')
            if source and (source['symbol_library_sha256'] != symbol_hashes[candidate['source']]
                           or source['footprint_sha256'] != fp_hashes[candidate['footprint_source']]
                           or source['source_footprint_property'] != candidate['source_footprint_identifier']):
                raise ValueError('Source changed during linked export')
            entries.append(entry)
            if progress and (n % 100 == 0 or n == len(selected)):
                progress(dict(processed=n, total=len(selected),
                              generated=sum(e['status'] in SUCCESS for e in entries),
                              complete_chains=sum(e['chain_complete'] for e in entries)))
        cache.clear()
        # Verify current selected bytes again before publication (including reused assets).
        _sources(symbol_source, symbol_hashes)
        _sources(footprint_source, fp_hashes)
        for relative, (asset, _) in assets.records.items():
            if file_digest(_portable_path(stl_root, relative)) != asset['sha256']:
                raise ValueError('Existing model changed during linked export: ' + relative)
        (stage / 'candidates.json').write_bytes(json_bytes(candidates))
        (stage / 'inputs.json').write_bytes(json_bytes(evidence))
        for label, root, audit_path in [('symbols', symbol_source, symbol_audit), ('footprints', footprint_source, footprint_audit)]:
            provenance_raw = (root / 'provenance.json').read_bytes() if (root / 'provenance.json').is_file() else None
            audit = json.loads(audit_path.read_bytes())
            if audit.get('source_provenance_sha256'):
                if provenance_raw is None or digest(provenance_raw) != audit['source_provenance_sha256']:
                    raise ValueError('Source provenance changed after audit')
            if provenance_raw is not None:
                provenance = json.loads(provenance_raw)
                directory = stage / 'upstream' / label
                directory.mkdir(parents=True)
                (directory / 'provenance.json').write_bytes(provenance_raw)
                license_record = provenance['license']
                raw = _portable_path(root, license_record['file']).read_bytes()
                if digest(raw) != license_record['sha256']:
                    raise ValueError('Upstream license changed')
                (directory / 'LICENSE.md').write_bytes(raw)
        summary = _summary(entries, candidates)
        (stage / 'linked-summary.json').write_bytes(json_bytes(summary))
        manifest = finish_bundle(stage, config, digest(json_bytes(evidence)), entries, assets, True, False)
        verify_mass(stage, manifest=manifest)
        if output.exists() or output.is_symlink():
            raise ValueError('Mass output appeared while staging')
        stage.rename(output)
    return summary


def _summary(entries, candidates):
    generated = [e for e in entries if e['status'] in SUCCESS]
    return dict(schema_version=1, kind='linked_component_preview',
                source_symbols=candidates['summary']['total'], candidates=len(entries),
                generated=len(generated), complete_model_dependencies=sum(e['chain_complete'] for e in generated),
                partial_or_no_model_dependencies=sum(not e['chain_complete'] for e in generated),
                refused=len(entries)-len(generated),
                unique_footprints=len({e['target_footprint'] for e in generated}),
                unique_existing_models=len({m['source_relative'] for e in generated for m in e['models']}),
                statuses=dict(sorted(Counter(e['status'] for e in entries).items())),
                errors=dict(sorted(Counter(e.get('error', {}).get('code', '') for e in entries if e['status'] not in SUCCESS).items())),
                excluded_candidate_statuses={k:v for k,v in candidates['summary']['statuses'].items() if k != 'eligible_for_linked_export'},
                cds_footprints_assigned=True, literal_number_mapping_verified=True,
                target_gui_validated=False, native_netlist_verified=False,
                model_alignment_validated=False, manufacturing_validated=False)


def verify_mass(root, *, manifest=None):
    root = Path(root)
    if root.is_symlink():
        raise ValueError('Linked preview root cannot be a symlink')
    manifest = verify_bundle(root) if manifest is None else manifest
    indexed = {r['path']: r['sha256'] for r in manifest['files']}
    if not {'candidates.json', 'inputs.json', 'linked-summary.json'} <= indexed.keys():
        raise ValueError('Missing linked preview evidence')
    candidates = json.loads((root / 'candidates.json').read_bytes())
    inputs = json.loads((root / 'inputs.json').read_bytes())
    if (inputs['kind'] != 'audited_linked_preview_inputs'
            or manifest['config_sha256'] != digest(json_bytes(inputs))
            or any(inputs[k] is not False for k in ('native_netlist_verified', 'target_gui_validated', 'model_alignment_validated'))
            or any(inputs[k] != candidates[k] for k in ('symbol_audit_sha256', 'footprint_audit_sha256'))):
        raise ValueError('Invalid linked preview input evidence')
    selected = {component_id(i['source'], i['symbol']): i for i in candidates['items'] if i['status'] == 'eligible_for_linked_export'}
    entries = manifest['components']
    if len(selected) != len(entries) or {e['id'] for e in entries} != set(selected):
        raise ValueError('Linked candidate coverage mismatch')
    target_contents = {}
    for entry in entries:
        if entry['status'] not in SUCCESS:
            continue
        candidate, source = selected[entry['id']], entry['source']
        footprint_hash = indexed[entry['footprint']]
        if target_contents.setdefault(entry['target_footprint'], footprint_hash) != footprint_hash:
            raise ValueError('Conflicting FPL contents for one native footprint name')
        if (source['symbol_library'] != candidate['source'] or source['symbol'] != candidate['symbol']
                or source['source_footprint_property'] != candidate['source_footprint_identifier']
                or source['selection'] != 'source_property'
                or source['symbol_library_sha256'] != inputs['symbol_sources'][candidate['source']]
                or source['footprint_sha256'] != inputs['footprint_sources'][candidate['footprint_source']]
                or entry['pin_mapping']['source_numbers'] != candidate['physical_numbers']):
            raise ValueError('Linked source/candidate identity mismatch')
    summary = _summary(entries, candidates)
    if json.loads((root / 'linked-summary.json').read_bytes()) != summary:
        raise ValueError('Linked preview summary mismatch')
    return summary


def archive_mass(root, archive):
    """Create a deterministic ZIP, check CRC and verify its independently extracted copy."""
    root, archive = Path(root), Path(archive)
    verify_mass(root)
    validate_output_path(archive, root / 'manifest.json', DEFAULT_STL_ROOT)
    if archive.exists() or archive.is_symlink() or archive.resolve().is_relative_to(root.resolve()):
        raise ValueError('Archive must be new and outside the linked preview')
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.linked-archive-', dir=archive.parent) as temporary:
        temporary = Path(temporary)
        target = temporary / 'preview.zip'
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as zipped:
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    info = zipfile.ZipInfo('linked-components-preview/' + path.relative_to(root).as_posix(), (1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    with path.open('rb') as source, zipped.open(info, 'w', force_zip64=True) as destination:
                        shutil.copyfileobj(source, destination, 1024*1024)
        with zipfile.ZipFile(target) as zipped:
            if zipped.testzip() is not None:
                raise ValueError('Linked archive CRC mismatch')
            zipped.extractall(temporary / 'relocated')
        verify_mass(temporary / 'relocated/linked-components-preview')
        if archive.exists() or archive.is_symlink():
            raise ValueError('Archive appeared while staging')
        target.rename(archive)
    return dict(bytes=archive.stat().st_size, sha256=file_digest(archive), crc_verified=True, relocated_verified=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    build = sub.add_parser('build')
    for name in ('symbol_source', 'symbol_batch', 'symbol_audit', 'footprint_source', 'footprint_batch', 'footprint_audit', 'output'):
        build.add_argument(name, type=Path)
    build.add_argument('--stl-root', type=Path, default=DEFAULT_STL_ROOT)
    verify = sub.add_parser('verify')
    verify.add_argument('root', type=Path)
    archive = sub.add_parser('archive')
    archive.add_argument('root', type=Path)
    archive.add_argument('archive', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == 'build':
            result = export_mass(args.symbol_source, args.symbol_batch, args.symbol_audit, args.footprint_source,
                                 args.footprint_batch, args.footprint_audit, args.output, stl_root=args.stl_root,
                                 progress=lambda value: print(json.dumps(value), flush=True))
        elif args.action == 'verify':
            result = verify_mass(args.root)
        else:
            result = archive_mass(args.root, args.archive)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except (ValueError, OSError, KeyError, TypeError, zipfile.BadZipFile) as error:
        print('Linked preview failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
