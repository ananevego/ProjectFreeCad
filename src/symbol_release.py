"""Portable audited CDS preview with per-symbol loss/source reports; no meshes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

from .library_corpus import sha256_file
from .library_release import member, encode_json
from .footprint_converter.batch import SUCCESS
from .footprint_converter.io import validate_output_path
from .footprint_converter.model_matching import DEFAULT_STL_ROOT

FLAGS = ('target_gui_validated', 'native_netlist_verified', 'physical_footprint_mapping_verified')


def build_release(source, batch, audit_path, output):
    source, batch, audit_path, output = map(Path, (source, batch, audit_path, output))
    validate_output_path(output, audit_path, DEFAULT_STL_ROOT)
    if (output.exists() or output.is_symlink() or output.resolve().is_relative_to(source.resolve())
            or output.resolve().is_relative_to(batch.resolve())):
        raise ValueError('Symbol preview output must be new and outside source/batch')
    manifest_raw = (batch / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    audit_raw = audit_path.read_bytes()
    audit = json.loads(audit_raw)
    provenance_raw = (source / 'provenance.json').read_bytes()
    provenance = json.loads(provenance_raw)
    if (audit.get('kind') != 'symbol_batch_audit' or audit.get('batch_manifest_sha256') != hashlib.sha256(manifest_raw).hexdigest()
            or audit.get('source_provenance_sha256') != hashlib.sha256(provenance_raw).hexdigest()
            or manifest.get('status') not in {'completed', 'completed_with_errors'}
            or not audit['summary']['source_inventory_complete'] or audit['summary']['unexpected_errors']
            or any(audit.get(flag) is not False for flag in FLAGS)):
        raise ValueError('Symbol preview requires matching complete audit, explicit native limits and no unexpected errors')
    pinned = {r['file']: r for r in provenance['files']}
    if len(pinned) != len(provenance['files']) or set(pinned) != {r['source'] for r in manifest['libraries']}:
        raise ValueError('Symbol provenance/library inventory mismatch')
    for library in manifest['libraries']:
        if sha256_file(member(source, library['source'])) != pinned[library['source']]['sha256'] or library['input_sha256'] != pinned[library['source']]['sha256']:
            raise ValueError('Symbol source changed after audit')
    audited = {(i['source'], i['symbol']): i for i in audit['items']}
    if len(audited) != len(audit['items']) or set(audited) != {(e['source'], e['symbol']) for e in manifest['entries']}:
        raise ValueError('Symbol audit/manifest identity mismatch')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.symbol-preview-', dir=output.parent) as temporary:
        staging = Path(temporary) / 'preview'
        staging.mkdir()
        files, catalog, failures = [], [], []
        def write(name, raw):
            path = member(staging, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            files.append(dict(file=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
        for entry in manifest['entries']:
            item = audited[entry['source'], entry['symbol']]
            if item['status'] != entry['status']:
                raise ValueError('Symbol preview status mismatch')
            if entry['status'] not in SUCCESS:
                if entry['output_current'] is not False:
                    raise ValueError('Refused symbol incorrectly marked current')
                failures.append({k: entry[k] for k in ('source', 'symbol', 'input_sha256', 'failure_category', 'error_type', 'errors')})
                continue
            if entry['output_current'] is not True or item['source_pin_records_validated'] is not True:
                raise ValueError('Symbol output is not current/audited')
            for key, sha_key in [('output_file', 'output_sha256'), ('report_file', 'report_sha256')]:
                raw = member(batch, entry[key]).read_bytes()
                if hashlib.sha256(raw).hexdigest() != entry[sha_key]:
                    raise ValueError('Symbol artifact changed after audit')
                write(entry[key], raw)
            catalog.append({k: entry[k] for k in ('source', 'symbol', 'input_sha256', 'output_file', 'output_sha256', 'report_file', 'report_sha256', 'readback', 'diagnostics')})
        license_record = provenance['license']
        license_raw = member(source, license_record['file']).read_bytes()
        if hashlib.sha256(license_raw).hexdigest() != license_record['sha256']:
            raise ValueError('Symbol source license changed')
        write('LICENSE.md', license_raw)
        write('provenance.json', provenance_raw)
        if (source / 'source-tree.json').exists():
            raw = (source / 'source-tree.json').read_bytes()
            if hashlib.sha256(raw).hexdigest() != provenance['source_tree_metadata']['sha256']:
                raise ValueError('Symbol source tree changed')
            write('source-tree.json', raw)
        write('audit.json', audit_raw)
        write('catalog.json', encode_json(catalog))
        write('failures.json', encode_json(failures))
        write('README.txt', (
            'KiCad 9 symbols -> Schemator 1.429: UNLINKED 2D PREVIEW\n'
            f'{len(catalog)} CDS generated; {len(failures)} refused source symbols.\n'
            'All emitted components retain the PART footprint placeholder.\n'
            'No footprint/pad/3D mapping, native GUI import, ERC or netlist verification is claimed.\n'
            'Full source/conversion/loss reports are included for every generated component.\n'
            'Explicit NC/hidden/common policies are recorded in audit.json and reports.\n'
            'Filename/source identifiers: catalog.json; all omissions: failures.json.\n'
            'Upstream source URLs/hashes and license/exception: provenance.json, LICENSE.md.\n'
        ).encode())
        release = dict(schema_version=1, kind='schemator_symbol_preview', source_revision=provenance['revision'],
                       generated=len(catalog), omitted=len(failures), total=len(manifest['entries']),
                       source_libraries=len(pinned), model_assets_included=False, footprint_binding='PART placeholder',
                       options=audit['options'], **{flag: False for flag in FLAGS}, files=files)
        if (release['generated'], release['omitted']) != (audit['summary']['generated'], audit['summary']['failed'] + audit['summary']['rejected_loss']):
            raise ValueError('Symbol preview counts differ from audit')
        (staging / 'release.json').write_bytes(encode_json(release))
        verify_release(staging)
        if output.exists() or output.is_symlink():
            raise ValueError('Symbol preview already exists')
        staging.rename(output)
    return release


def verify_release(output):
    output = Path(output)
    if output.is_symlink():
        raise ValueError('Symbol preview root cannot be a symlink')
    release = json.loads(member(output, 'release.json').read_bytes())
    if (release.get('kind') != 'schemator_symbol_preview' or release.get('schema_version') != 1
            or release.get('footprint_binding') != 'PART placeholder' or release.get('model_assets_included') is not False
            or any(release.get(flag) is not False for flag in FLAGS)):
        raise ValueError('Invalid symbol preview or unsupported native/binding claim')
    indexed, folded = {}, set()
    for record in release['files']:
        if record['file'].casefold() in folded:
            raise ValueError('Duplicate symbol preview path')
        path = member(output, record['file'])
        if not path.is_file() or path.stat().st_size != record['bytes'] or sha256_file(path) != record['sha256']:
            raise ValueError('Symbol preview checksum/size mismatch')
        indexed[record['file']] = record['sha256']
        folded.add(record['file'].casefold())
    catalog = json.loads(member(output, 'catalog.json').read_bytes())
    failures = json.loads(member(output, 'failures.json').read_bytes())
    ids = [(e['source'], e['symbol']) for e in catalog + failures]
    cds = {e['output_file']: e['output_sha256'] for e in catalog}
    reports = {e['report_file']: e['report_sha256'] for e in catalog}
    if (len(catalog) != release['generated'] or len(failures) != release['omitted']
            or len(ids) != release['total'] or len(set(ids)) != len(ids)
            or len(cds) != len(catalog) or len(reports) != len(catalog)
            or cds != {k: v for k, v in indexed.items() if k.endswith('.cds')}
            or any(indexed.get(k) != v for k, v in reports.items())):
        raise ValueError('Symbol preview catalog/count mismatch')
    actual = {p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file() or p.is_symlink()}
    if actual != set(indexed) | {'release.json'}:
        raise ValueError('Unindexed/missing symbol preview files')
    return release


def archive_release(output, archive):
    output, archive = Path(output), Path(archive)
    verify_release(output)
    validate_output_path(archive, output / 'release.json', DEFAULT_STL_ROOT)
    if archive.exists() or archive.is_symlink() or archive.resolve().is_relative_to(output.resolve()):
        raise ValueError('Symbol archive must be new and outside preview')
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.symbol-zip-', dir=archive.parent) as temporary:
        path = Path(temporary) / 'preview.zip'
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
            for file in sorted(output.rglob('*')):
                if file.is_file():
                    info = zipfile.ZipInfo('schemator-symbols-preview/' + file.relative_to(output).as_posix(), (1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    zipped.writestr(info, file.read_bytes())
        if archive.exists() or archive.is_symlink():
            raise ValueError('Symbol archive already exists')
        path.rename(archive)
    return dict(bytes=archive.stat().st_size, sha256=sha256_file(archive))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'batch', 'audit', 'output'):
        parser.add_argument(name, type=Path, nargs='?')
    parser.add_argument('--verify', type=Path)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.verify:
            result = verify_release(args.verify)
        else:
            if any(getattr(args, name) is None for name in ('source', 'batch', 'audit', 'output')):
                parser.error('source, batch, audit and output required')
            result = build_release(args.source, args.batch, args.audit, args.output)
        if args.archive:
            print(json.dumps(archive_release(args.verify or args.output, args.archive)))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('Symbol preview failed: ' + str(error), file=sys.stderr)
        return 1
    print(f"Symbol preview verified: {result['generated']} CDS, {result['omitted']} omitted; footprint binding unresolved")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
