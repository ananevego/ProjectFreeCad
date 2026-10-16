"""Package an audited full footprint batch as a portable 2D preview library.

Meshes are external dependencies and are never opened or copied here. Only
current, hash-checked successful FPL files enter the library. Every omitted
source remains in the failure catalog; native validation is explicitly pending.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import zipfile

from .library_corpus import safe_path, sha256_file
from .footprint_converter.batch import SUCCESS
from .footprint_converter.io import validate_output_path
from .footprint_converter.model_matching import DEFAULT_STL_ROOT

NATIVE_FLAGS = ('target_gui_validated', 'model_geometry_validated', 'manufacturing_validated', 'native_netlist_verified')


def member(base, relative):
    path = safe_path(relative)
    candidate = base.joinpath(*path.parts)
    if any(base.joinpath(*path.parts[:i]).is_symlink() for i in range(1, len(path.parts) + 1)):
        raise ValueError('Release input cannot contain symlinks')
    return candidate


def encode_json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def primary_failure(item):
    category = item['failure_category']
    if category != 'UNCLASSIFIED_FAILURE':
        return category
    if item['error_type'] == 'UnicodeEncodeError':
        return 'ENCODING_UNREPRESENTABLE'
    message = ' '.join(item['errors'])
    for text, code in [('Non-identity KiCad 3D transform', 'MODEL_TRANSFORM_REQUIRES_OVERRIDE'),
                       ('at least one pad/hole', 'NO_SUPPORTED_PAD_OR_GRAPHIC'),
                       ('non-centred justification', 'TEXT_JUSTIFICATION_UNSUPPORTED'),
                       ('custom/bold/italic font', 'TEXT_FONT_UNSUPPORTED'),
                       ('Duplicate reference text', 'TEXT_FIELD_DUPLICATE'),
                       ('stores integer angles', 'ANGLE_NONINTEGER_UNSUPPORTED'),
                       ('Malformed pad drill', 'DRILL_MALFORMED'),
                       ('quoted field cannot safely represent', 'QUOTED_FIELD_UNREPRESENTABLE'),
                       ('unsupported rect_delta', 'PAD_TRAPEZOID_UNSUPPORTED'),
                       ('Anisotropic text size', 'TEXT_ANISOTROPIC_UNSUPPORTED'),
                       ('coincident or collinear', 'ARC_DEGENERATE'),
                       ('Filled graphics require more than', 'FILL_COMPLEXITY_LIMIT'),
                       ('Filled polygon', 'FILL_GEOMETRY_OUTSIDE_PROFILE'),
                       ('Filled circle', 'FILL_GEOMETRY_OUTSIDE_PROFILE')]:
        if text in message:
            return code
    return category


def build_release(source, batch, audit_path, output):
    source, batch, audit_path, output = map(Path, (source, batch, audit_path, output))
    validate_output_path(output, audit_path, DEFAULT_STL_ROOT)
    if (output.exists() or output.is_symlink() or output.resolve().is_relative_to(source.resolve())
            or output.resolve().is_relative_to(batch.resolve())):
        raise ValueError('Release output must be a new directory outside source and batch')
    manifest_raw = (batch / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    audit_raw = audit_path.read_bytes()
    audit = json.loads(audit_raw)
    provenance_raw = (source / 'provenance.json').read_bytes()
    if (manifest.get('status') not in {'completed', 'completed_with_errors'}
            or audit.get('kind') != 'footprint_batch_audit'
            or audit.get('batch_manifest_sha256') != hashlib.sha256(manifest_raw).hexdigest()
            or audit.get('source_provenance_sha256') != hashlib.sha256(provenance_raw).hexdigest()
            or any(audit.get(flag) is not False for flag in NATIVE_FLAGS)):
        raise ValueError('Release requires a matching completed audit with native checks pending')
    audited = {item['source']: item for item in audit['items']}
    if len(audited) != len(audit['items']) or set(audited) != {e['source'] for e in manifest['entries']}:
        raise ValueError('Audit/manifest source inventory mismatch')
    provenance = json.loads(provenance_raw)
    pinned = {record['file']: record for record in provenance['files']}
    if len(pinned) != len(provenance['files']) or set(pinned) != set(audited):
        raise ValueError('Release must cover every source in its provenance')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.release-', dir=output.parent) as temporary:
        staging = Path(temporary) / 'library'
        staging.mkdir()
        files, catalog, failures = [], [], []

        def write(relative, raw):
            destination = member(staging, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            files.append(dict(file=relative, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))

        for entry in manifest['entries']:
            name = entry['source']
            item = audited[name]
            if (entry['status'] != item['status'] or entry['input_sha256'] != item['input_sha256']
                    or entry['input_sha256'] != pinned[name]['sha256']
                    or sha256_file(member(source, name)) != entry['input_sha256']):
                raise ValueError('Source changed since audit: ' + name)
            if entry['status'] not in SUCCESS:
                if entry.get('output_current') is not False:
                    raise ValueError('Failed output incorrectly marked current')
                failures.append(dict(source=name, input_sha256=entry['input_sha256'],
                                     category=primary_failure(item), errors=item['errors'], error_type=item['error_type']))
                continue
            if (entry.get('output_current') is not True or item.get('target_records_validated') is not True
                    or entry['output_sha256'] != item['output_sha256']):
                raise ValueError('Successful output is not audited/current')
            raw = member(batch, entry['output_file']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry['output_sha256']:
                raise ValueError('FPL changed since audit: ' + name)
            category = safe_path(name).parts[0] if len(safe_path(name).parts) > 1 else 'Uncategorized'
            relative = f'libraries/{category}/{entry["target_name"]}.fpl'
            write(relative, raw)
            catalog.append(dict(source=name, input_sha256=entry['input_sha256'], file=relative,
                                output_sha256=entry['output_sha256'], status=entry['status'],
                                matched_external_models=item['matched_models'],
                                loss_codes=sorted({d['code'] for d in entry['diagnostics'] if d['severity'] == 'loss'})))
        if len(catalog) != audit['summary']['generated'] or len(catalog) + len(failures) != audit['summary']['total']:
            raise ValueError('Release counts differ from audit')
        license_record = provenance['license']
        license_raw = member(source, license_record['file']).read_bytes()
        if hashlib.sha256(license_raw).hexdigest() != license_record['sha256']:
            raise ValueError('Upstream license changed')
        write('LICENSE.md', license_raw)
        write('provenance.json', provenance_raw)
        tree_path = source / 'source-tree.json'
        if tree_path.exists():
            tree_raw = tree_path.read_bytes()
            if hashlib.sha256(tree_raw).hexdigest() != provenance['source_tree_metadata']['sha256']:
                raise ValueError('Source tree metadata changed')
            write('source-tree.json', tree_raw)
        write('catalog.json', encode_json(catalog))
        write('failures.json', encode_json(failures))
        write('audit.json', audit_raw)
        write('README.txt', (
            'KiCad -> FreePCB2 2.428: complete-corpus 2D PREVIEW\n'
            'Source revision: ' + provenance['revision'] + '\n'
            f'{len(catalog)} generated footprints; {len(failures)} omitted sources listed in failures.json.\n'
            'Known losses and limitations are listed in catalog.json and audit.json.\n'
            'Library identifiers are stable batch names; catalog.json maps original names.\n'
            'Use libraries/<source category>/ in FreePCB2. Target encoding: ' + manifest['options']['encoding'] + '.\n'
            'GUI load/save, netlist, Gerber and physical 3D alignment remain UNVERIFIED.\n'
            'Existing OpenSCAD model references remain in FPL; STL/STEP assets are NOT included.\n'
            'To use them, provide the corresponding existing category .3dshapes folder, in MM units.\n'
            'This package does not claim a portable or validated 3D library.\n'
            'Sources and KiCad Libraries license/exception: provenance.json and LICENSE.md.\n'
        ).encode('utf-8'))
        release = dict(schema_version=1, kind='footprint_library_preview', source_revision=provenance['revision'],
                       generated=len(catalog), omitted=len(failures), source_files=len(audited),
                       source_batch_manifest_sha256=audit['batch_manifest_sha256'],
                       model_assets_included=False, options=audit['options'],
                       **{flag: False for flag in NATIVE_FLAGS}, files=files)
        (staging / 'release.json').write_bytes(encode_json(release))
        verify_release(staging)
        if output.exists() or output.is_symlink():
            raise ValueError('Release output already exists')
        staging.rename(output)
    return release


def verify_release(output):
    output = Path(output)
    if output.is_symlink():
        raise ValueError('Release root cannot be a symlink')
    release = json.loads(member(output, 'release.json').read_bytes())
    if (release.get('kind') != 'footprint_library_preview' or release.get('schema_version') != 1
            or release.get('model_assets_included') is not False
            or any(release.get(flag) is not False for flag in NATIVE_FLAGS)):
        raise ValueError('Invalid preview release or unsupported validation claim')
    paths = set()
    for record in release['files']:
        name = record['file']
        if name.casefold() in paths:
            raise ValueError('Duplicate/case-colliding release path')
        paths.add(name.casefold())
        path = member(output, name)
        if not path.is_file() or path.stat().st_size != record['bytes'] or sha256_file(path) != record['sha256']:
            raise ValueError('Release file checksum/size mismatch: ' + name)
    catalog = json.loads(member(output, 'catalog.json').read_bytes())
    failures = json.loads(member(output, 'failures.json').read_bytes())
    sources = [item['source'] for item in catalog + failures]
    fpls = {item['file']: item['output_sha256'] for item in catalog}
    indexed = {r['file']: r['sha256'] for r in release['files'] if r['file'].endswith('.fpl')}
    if (len(catalog) != release['generated'] or len(failures) != release['omitted']
            or len(sources) != len(set(sources)) or len(sources) != release['source_files']
            or len(fpls) != len(catalog) or fpls != indexed):
        raise ValueError('Release catalog/count mismatch')
    actual = {path.relative_to(output).as_posix() for path in output.rglob('*') if path.is_file() or path.is_symlink()}
    if actual != {r['file'] for r in release['files']} | {'release.json'}:
        raise ValueError('Unindexed or missing release files')
    return release


def archive_release(output, archive):
    output, archive = Path(output), Path(archive)
    verify_release(output)
    validate_output_path(archive, output / 'release.json', DEFAULT_STL_ROOT)
    if archive.exists() or archive.is_symlink() or archive.resolve().is_relative_to(output.resolve()):
        raise ValueError('Archive must be new and outside the release')
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.release-zip-', dir=archive.parent) as temporary:
        temporary_zip = Path(temporary) / 'library.zip'
        with zipfile.ZipFile(temporary_zip, 'w', compression=zipfile.ZIP_DEFLATED) as target:
            for path in sorted(output.rglob('*')):
                if path.is_file():
                    info = zipfile.ZipInfo('freepcb-footprints-preview/' + path.relative_to(output).as_posix(), (1980, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    target.writestr(info, path.read_bytes())
        if archive.exists() or archive.is_symlink():
            raise ValueError('Archive already exists')
        temporary_zip.rename(archive)
    return dict(bytes=archive.stat().st_size, sha256=sha256_file(archive))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path, nargs='?')
    parser.add_argument('batch', type=Path, nargs='?')
    parser.add_argument('audit', type=Path, nargs='?')
    parser.add_argument('output', type=Path, nargs='?')
    parser.add_argument('--verify', type=Path)
    parser.add_argument('--archive', type=Path)
    args = parser.parse_args(argv)
    try:
        if args.verify:
            result = verify_release(args.verify)
        else:
            if any(value is None for value in (args.source, args.batch, args.audit, args.output)):
                parser.error('source, batch, audit and output are required')
            result = build_release(args.source, args.batch, args.audit, args.output)
        if args.archive:
            print(json.dumps(archive_release(args.verify or args.output, args.archive), sort_keys=True))
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as error:
        print('Library release failed: ' + str(error), file=sys.stderr)
        return 1
    print(f"2D preview verified: {result['generated']} generated, {result['omitted']} omitted; native validation pending")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
