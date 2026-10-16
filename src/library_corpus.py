"""Prepare a complete pinned KiCad footprint/symbol corpus from a local archive.

Only verified footprints and the upstream license are copied. No archive paths
are extracted directly, no meshes are accessed, and an existing output is never
overwritten. Downloading is deliberately separate from verification.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile
import tempfile

from .footprint_converter.io import validate_output_path
from .footprint_converter.model_matching import DEFAULT_STL_ROOT

REVISION = '51f8a59ed7d5f3bab9bb296c7b767bb033f3ba4c'
TREE_SHA256 = '181483cc4da9a004fb7ab1dc129c1acbbfd12c0ca98e471a5c23491f6f2317de'
FOOTPRINT_COUNT = 15464
ARCHIVE_ROOT = 'kicad-footprints-' + REVISION
ARCHIVE_URL = 'https://codeload.github.com/KiCad/kicad-footprints/tar.gz/' + REVISION
TREE_URL = 'https://api.github.com/repos/KiCad/kicad-footprints/git/trees/' + REVISION + '?recursive=1'
RAW_URL = 'https://raw.githubusercontent.com/KiCad/kicad-footprints/' + REVISION + '/'
SYMBOLS_REVISION = 'a9012d8971ef2ea3243ffc9f19a5b4f153d8b334'
SYMBOLS_TREE_SHA256 = 'e83d105e517862acb1331ed6399578bd30cbc3bbf0dff1140ea310c8a41a5cc4'
SYMBOL_LIBRARY_COUNT = 224


def sha256_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest() if hasattr(hashlib, 'file_digest') else _stream_sha(stream)


def _stream_sha(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
    return digest.hexdigest()


def safe_path(value):
    path = PurePosixPath(value)
    if (not value or '\\' in value or ':' in value or path.is_absolute()
            or '..' in path.parts or path.as_posix() != value.rstrip('/')):
        raise ValueError('Unsafe corpus path: ' + value)
    return path


def prepare_corpus(archive, tree_file, output, *, kind='footprints'):
    if kind not in {'footprints', 'symbols'}:
        raise ValueError('Unknown corpus kind')
    revision = REVISION if kind == 'footprints' else SYMBOLS_REVISION
    tree_sha = TREE_SHA256 if kind == 'footprints' else SYMBOLS_TREE_SHA256
    count = FOOTPRINT_COUNT if kind == 'footprints' else SYMBOL_LIBRARY_COUNT
    suffix = '.kicad_mod' if kind == 'footprints' else '.kicad_sym'
    project = 'kicad-' + kind
    archive_root = project + '-' + revision
    archive_url = 'https://codeload.github.com/KiCad/' + project + '/tar.gz/' + revision
    tree_url = 'https://api.github.com/repos/KiCad/' + project + '/git/trees/' + revision + '?recursive=1'
    raw_url = 'https://raw.githubusercontent.com/KiCad/' + project + '/' + revision + '/'
    archive, tree_file, output = Path(archive), Path(tree_file), Path(output)
    validate_output_path(output, archive, DEFAULT_STL_ROOT)
    if output.exists() or output.is_symlink():
        raise ValueError('Corpus output must be a new directory')
    tree_raw = tree_file.read_bytes()
    if hashlib.sha256(tree_raw).hexdigest() != tree_sha:
        raise ValueError('Pinned source tree checksum mismatch')
    tree = json.loads(tree_raw)
    if tree.get('sha') != revision or tree.get('truncated') is not False:
        raise ValueError('Source tree must be complete and match the pinned revision')
    selected = {}
    folded = set()
    for item in tree['tree']:
        name = item['path']
        if not (name.endswith(suffix) or name == 'LICENSE.md'):
            continue
        safe_path(name)
        if item['type'] != 'blob' or item['mode'] not in {'100644', '100755'} or name.casefold() in folded:
            raise ValueError('Invalid, duplicate or case-colliding source tree member')
        selected[name] = item
        folded.add(name.casefold())
    if len(selected) != count + 1 or 'LICENSE.md' not in selected:
        raise ValueError('Pinned footprint/license inventory mismatch')
    provenance = dict(schema_version=1, project='KiCad community / ' + project,
                      revision=revision, modified=False, selection='all ' + suffix + ' files in the complete pinned tree',
                      source_tree_metadata=dict(url=tree_url, sha256=tree_sha, truncated=False,
                                                **{('footprint_count' if kind == 'footprints' else 'library_count'): count}),
                      archive=dict(url=archive_url, sha256=sha256_file(archive), bytes=archive.stat().st_size),
                      files=[])
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.corpus-', dir=output.parent) as temporary:
        staging = Path(temporary) / 'source'
        staging.mkdir()
        seen, found = set(), set()
        with tarfile.open(archive, 'r:gz') as tar:
            for member in tar:
                path = safe_path(member.name)
                if path.parts[0] != archive_root or member.name in seen:
                    raise ValueError('Unexpected archive root or duplicate member')
                seen.add(member.name)
                if not (member.isdir() or member.isfile()):
                    raise ValueError('Archive links and special files are unsupported')
                relative = PurePosixPath(*path.parts[1:]).as_posix()
                if relative not in selected:
                    continue
                expected = selected[relative]
                if not member.isfile() or member.size != expected['size']:
                    raise ValueError('Archive member type/size mismatch: ' + relative)
                with tar.extractfile(member) as stream:
                    data = stream.read()
                blob = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
                if len(data) != expected['size'] or blob != expected['sha']:
                    raise ValueError('Pinned Git blob mismatch: ' + relative)
                destination = staging.joinpath(*PurePosixPath(relative).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(data)
                record = dict(file=relative, bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                              git_blob_sha1=blob, url=raw_url + relative)
                if relative == 'LICENSE.md':
                    provenance['license'] = record
                else:
                    provenance['files'].append(record)
                found.add(relative)
        if found != set(selected):
            raise ValueError('Archive is missing pinned source members')
        provenance['files'].sort(key=lambda record: record['file'])
        provenance['category_populations'] = dict(sorted(Counter(
            PurePosixPath(record['file']).parts[0] for record in provenance['files']).items()))
        (staging / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (staging / 'source-tree.json').write_bytes(tree_raw)
        if output.exists() or output.is_symlink():
            raise ValueError('Corpus output already exists')
        staging.rename(output)
    return provenance


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('tree', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--kind', choices=('footprints', 'symbols'), default='footprints')
    args = parser.parse_args(argv)
    try:
        result = prepare_corpus(args.archive, args.tree, args.output, kind=args.kind)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError) as error:
        print('Corpus preparation failed: ' + str(error), file=sys.stderr)
        return 1
    print(f"Verified corpus: {len(result['files'])} {args.kind} source files; license retained")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
