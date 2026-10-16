"""Deterministic footprint batches with per-item cache, reports and recovery.

Run: python -m src.footprint_converter.batch INPUT_DIR OUTPUT_DIR [--resume].
No mesh contents are read; each FPL remains a standalone target library.
"""
from __future__ import annotations

import argparse
import codecs
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys

from .errors import ConversionError, LossyConversionError, PadGeometryError
from .format_rules import quote
from .io import atomic_write, validate_output_path
from .model import ApertureSettings, ModelTransform, ONE, ZERO
from .model_matching import DEFAULT_STL_ROOT
from .parser import parse_sexpr
from .pipeline import convert_detailed

CHECKPOINT_INTERVAL = 50
SUCCESS = {'generated', 'generated_with_loss'}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                       allow_nan=False) + '\n').encode('utf-8')


def engine_fingerprint() -> str:
    # Includes pipeline/matcher/parser/writer and batch/cache implementation.
    data = b''.join(p.name.encode() + b'\0' + p.read_bytes()
                    for p in sorted(Path(__file__).parent.glob('*.py')))
    return digest(data)


def item_name(relative: str) -> str:
    """ASCII, Windows-safe, stable across ordering and source-root relocation."""
    label = re.sub(r'[^A-Za-z0-9_.-]+', '_', relative.removesuffix('.kicad_mod'))
    return 'fp_' + label[:60].strip('._-') + '_' + digest(relative.encode('utf-8'))[:16]


def discover(root: Path) -> list[Path]:
    files = []
    def walk_error(error):
        raise error
    for folder, directories, names in os.walk(root, followlinks=False, onerror=walk_error):
        directories[:] = sorted(d for d in directories if not (Path(folder)/d).is_symlink())
        files.extend(Path(folder)/name for name in names if name.endswith('.kicad_mod'))
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def model_dependencies(root: list, stl_root: Path) -> list[dict]:
    """Fingerprint only candidate paths and stat metadata, including missing STL.

    Conservative: hidden references are also recorded, so a model change can
    trigger extra regeneration. Source bytes cover transforms and hide flags.
    """
    dependencies = []
    base = stl_root.resolve()
    for node in root:
        if not isinstance(node, list) or len(node) < 2 or node[0] != 'model' or not isinstance(node[1], str):
            continue
        reference = node[1]
        path = PurePosixPath(reference.replace('\\', '/'))
        indices = [i for i, part in enumerate(path.parts) if part.endswith('.3dshapes')]
        entry = {'reference': reference, 'candidate': None}
        if len(indices) == 1 and path.suffix.lower() in {'.step', '.stp', '.wrl', '.stl'}:
            relative = PurePosixPath(*path.parts[indices[0]:]).with_suffix('.stl')
            if '..' not in relative.parts and len(relative.parts) == 2:
                candidate = base.joinpath(*relative.parts).resolve()
                entry['candidate'] = str(candidate)
                if not candidate.is_relative_to(base):
                    entry['state'] = 'outside_root'
                elif candidate.is_file():
                    stat = candidate.stat()
                    entry.update(state='file', size=stat.st_size, mtime_ns=stat.st_mtime_ns,
                                 ctime_ns=stat.st_ctime_ns, inode=stat.st_ino)
                else:
                    entry['state'] = 'missing'
        dependencies.append(entry)
    return dependencies


def read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_bytes())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, UnicodeError):
        return None


def valid_cache(entry: dict | None) -> bool:
    if not entry or not isinstance(entry.get('status'), str) or entry['status'] not in SUCCESS:
        return False
    diagnostics = entry.get('diagnostics')
    return entry.get('output_current') is True and isinstance(diagnostics, list) and all(
        isinstance(d, dict) and all(isinstance(d.get(k), str) for k in ('code', 'severity', 'message'))
        for d in diagnostics)


def validate_destination(path: Path, output: Path, source: Path, stl_root: Path) -> None:
    validate_output_path(path, source, stl_root)
    if not path.resolve().is_relative_to(output) or path.is_symlink():
        raise ConversionError(f'Batch artifact escapes output directory or is a symlink: {path}')
    cursor = output
    for part in path.relative_to(output).parts:
        cursor /= part
        if cursor.is_symlink():
            raise ConversionError(f'Batch artifact directory contains a symlink: {cursor}')
    if path.resolve().is_relative_to(source):
        raise ConversionError('Batch cannot write inside the input directory')


@contextmanager
def batch_lock(path: Path):
    """OS advisory lock: released on interruption/process death, no stale PID lock."""
    file = path.open('a+b')
    acquired = False
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                if file.tell() == 0:
                    file.write(b'0')
                    file.flush()
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ConversionError('Another batch is using this output directory') from exc
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == 'nt':
                file.seek(0)
                msvcrt.locking(file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(file.fileno(), fcntl.LOCK_UN)
        file.close()


def summary(entries: list[dict]) -> dict:
    statuses = Counter(e['status'] for e in entries)
    codes = Counter()
    for entry in entries:
        codes.update(set(d['code'] for d in entry.get('diagnostics', [])))
    generated = sum(statuses[s] for s in SUCCESS)
    return {'total': len(entries), 'generated': generated,
            'generated_without_known_loss': statuses['generated'],
            'generated_with_loss': statuses['generated_with_loss'],
            'failed': statuses['failed'], 'rejected_loss': statuses['rejected_loss'],
            'pending': statuses['pending'], 'reused': sum(e.get('reused', False) for e in entries),
            'generation_percent': round(100 * generated / len(entries), 2) if entries else 0,
            'diagnostic_item_counts': dict(sorted(codes.items()))}


def run_batch(input_dir: Path, output_dir: Path, *, resume: bool = False,
              limit: int | None = None, stl_root: Path = DEFAULT_STL_ROOT,
              encoding: str = 'cp1251', curve_tolerance: float = 0.01,
              fill_tolerance: float = 0.01, strict: bool = False,
              text_variables: dict[str, str] | None = None,
              aperture_defaults: ApertureSettings | None = None,
              model_transform: ModelTransform | None = None,
              description_policy: str = 'preserve') -> dict:
    """Convert selected files; errors are isolated, KeyboardInterrupt propagates.

    Global input/path/configuration/manifest failures happen before artifact
    replacement. On item failure, an old FPL may remain; manifest marks it stale.
    """
    source, output, models = Path(input_dir).resolve(), Path(output_dir).resolve(), Path(stl_root).resolve()
    if not source.is_dir():
        raise ConversionError('Batch input must be an existing directory')
    if output.is_relative_to(source) or source.is_relative_to(output):
        raise ConversionError('Batch input and output directories must be disjoint')
    validate_output_path(output, source, models)
    if not math.isfinite(curve_tolerance) or curve_tolerance <= 0.00001:
        raise ConversionError('Curve tolerance must be greater than 0.00001 mm')
    if not math.isfinite(fill_tolerance) or not 0.00002 < fill_tolerance <= 1073:
        raise ConversionError('Fill tolerance must be in (0.00002, 1073] mm')
    if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0):
        raise ConversionError('Batch limit must be a positive integer')
    encoding = codecs.lookup(encoding).name
    variables = dict(text_variables or {})
    for key, value in variables.items():
        if not isinstance(key, str) or not key or not isinstance(value, str):
            raise ConversionError('Text bindings must have nonempty string names and string values')
        quote(value)
    defaults = aperture_defaults or ApertureSettings()
    if description_policy not in {'preserve', 'ascii-escape-with-loss'}:
        raise ConversionError('Unknown description policy')
    if any(v is not None and not math.isfinite(v) for v in asdict(defaults).values()):
        raise ConversionError('Non-finite aperture defaults')
    if model_transform is not None:
        vectors = (model_transform.translation, model_transform.rotation, model_transform.scale)
        if any(len(v) != 3 for v in vectors) or not all(math.isfinite(n) for v in vectors for n in v) or 0 in model_transform.scale:
            raise ConversionError('Invalid target model transform')
    options = dict(stl_root=models, curve_tolerance=curve_tolerance, fill_tolerance=fill_tolerance,
                   strict=strict, text_variables=variables, aperture_defaults=defaults,
                   model_transform=model_transform, description_policy=description_policy)
    config = dict(options, stl_root=str(models), aperture_defaults=asdict(defaults),
                  model_transform=asdict(model_transform) if model_transform else None,
                  encoding=encoding)
    fingerprint = digest(json_bytes({'options': config, 'engine': engine_fingerprint()}))
    files = discover(source)
    total_discovered = len(files)
    if limit:
        files = files[:limit]
    if not files:
        raise ConversionError('No .kicad_mod files found')
    entries, names = [], set()
    for path in files:
        relative = path.relative_to(source).as_posix()
        name = item_name(relative)
        if name.casefold() in names:
            raise ConversionError(f'Batch naming collision: {relative}')
        names.add(name.casefold())
        entries.append({'source': relative, 'target_name': name, 'status': 'pending',
                        'output_file': f'footprints/{name}.fpl', 'report_file': f'reports/{name}.report.json',
                        'state_file': f'state/{name}.json', 'output_current': False})
    manifest_path = output/'manifest.json'
    lock_path = output/'.batch.lock'
    for path in (manifest_path, lock_path):
        validate_destination(path, output, source, models)
    for entry in entries:
        for key in ('output_file', 'report_file', 'state_file'):
            validate_destination(output/entry[key], output, source, models)
    # Creating the directory/lock does not alter any conversion artifacts.
    output.mkdir(parents=True, exist_ok=True)
    with batch_lock(lock_path):
        previous = read_json(manifest_path)
        if manifest_path.exists() and (previous is None or previous.get('kind') != 'footprint_batch'
                                      or previous.get('schema_version') != 1
                                      or previous.get('input_root') != str(source)
                                      or not isinstance(previous.get('entries'), list)
                                      or not isinstance(previous.get('artifact_owners', {}), dict)):
            raise ConversionError('Existing batch manifest is invalid or belongs to a different input root')
        owned = dict(previous.get('artifact_owners', {})) if previous else {}
        if previous:
            for old in previous['entries']:
                if isinstance(old, dict) and isinstance(old.get('source'), str):
                    owned[old['source']] = old
        for entry in entries:
            old = owned.get(entry['source'], {})
            if not isinstance(old, dict):
                raise ConversionError('Invalid artifact ownership record')
            for key in ('output_file', 'report_file', 'state_file'):
                if (output/entry[key]).exists() and old.get(key) != entry[key]:
                    raise ConversionError(f'Refusing to overwrite an unowned batch artifact: {entry[key]}')
        removed = sorted(set(owned) - {e['source'] for e in entries})
        for entry in entries:
            owned[entry['source']] = {k: entry[k] for k in ('output_file', 'report_file', 'state_file')}
        manifest = {'schema_version': 1, 'kind': 'footprint_batch', 'status': 'running',
                    'input_root': str(source), 'output_root': str(output),
                    'configuration_fingerprint': fingerprint, 'options': config,
                    'discovered': total_discovered, 'selected': len(files), 'limit': limit,
                    'entries': entries, 'not_selected_previous_sources': removed,
                    'artifact_owners': owned,
                    'target_gui_validated': False}
        def checkpoint(status='running'):
            manifest['status'] = status
            manifest['summary'] = summary(entries)
            atomic_write(manifest_path, json_bytes(manifest))
        # Preclaim planned paths before any replacement: interrupted writes can
        # be safely repaired on a later run even before the first state commit.
        checkpoint()
        next_checkpoint = CHECKPOINT_INTERVAL
        for index, (path, entry) in enumerate(zip(files, entries), 1):
            destination, report_path, state_path = (output/entry[key] for key in ('output_file', 'report_file', 'state_file'))
            report = None
            try:
                if path.is_symlink() or not path.resolve().is_relative_to(source):
                    raise ConversionError('Symlink/outside-root input footprint is unsupported')
                data = path.read_bytes()
                entry['input_sha256'] = digest(data)
                root = parse_sexpr(data.decode('utf-8'))
                entry['source_footprint'] = root[1] if len(root) > 1 and isinstance(root[1], str) else None
                entry['model_dependencies'] = model_dependencies(root, models)
                cached = read_json(state_path) if resume else None
                if (valid_cache(cached) and cached.get('configuration_fingerprint') == fingerprint
                        and cached.get('input_root') == str(source)
                        and all(cached.get(k) == entry.get(k) for k in ('source', 'target_name', 'input_sha256',
                                   'model_dependencies', 'source_footprint', 'output_file', 'report_file', 'state_file'))
                        and destination.is_file() and report_path.is_file()
                        and digest(destination.read_bytes()) == cached.get('output_sha256')
                        and digest(report_path.read_bytes()) == cached.get('report_sha256')):
                    entry.update(cached, reused=True)
                    # Cache stores input_root/configuration for recovery, not a second manifest.
                else:
                    result = convert_detailed(root, entry['target_name'], **options)
                    encoded = result.fpl.encode(encoding)
                    report = dict(result.report, input_file=str(path), output_file=str(destination),
                                  output_encoding=encoding)
                    atomic_write(destination, encoded)
                    entry.update(status=result.report['status'], output_current=True,
                                 output_sha256=digest(encoded), diagnostics=result.report['diagnostics'], reused=False)
            except Exception as exc:
                # A malformed source can expose a parser TypeError, and a
                # pipeline bug must not abort unrelated files. Record its type;
                # interruption/process exit still propagate (BaseException).
                report = dict(exc.report) if isinstance(exc, (LossyConversionError, PadGeometryError)) else {'schema_version': 1, 'status': 'failed'}
                report['errors'] = [str(exc)]
                report['error_type'] = type(exc).__name__
                report['unexpected_error'] = not isinstance(exc, (ValueError, OSError, LookupError))
                entry.update(status=report['status'], errors=[str(exc)],
                             error_type=report['error_type'], unexpected_error=report['unexpected_error'],
                             diagnostics=report.get('diagnostics', []), output_current=False, reused=False)
                entry.pop('output_sha256', None)
            if report is not None:
                try:
                    encoded_report = json_bytes(report)
                    atomic_write(report_path, encoded_report)
                    entry['report_sha256'] = digest(encoded_report)
                    state = dict(entry, configuration_fingerprint=fingerprint, input_root=str(source))
                    atomic_write(state_path, json_bytes(state))
                except (ValueError, OSError) as exc:
                    entry.update(status='failed', output_current=False, reused=False,
                                 errors=entry.get('errors', []) + [f'Unable to commit report/state: {exc}'])
                    entry.pop('output_sha256', None)
            # State is committed for every item. Grow snapshot spacing so
            # rewriting a large manifest does not incur quadratic I/O.
            if index == next_checkpoint:
                checkpoint()
                next_checkpoint *= 2
        checkpoint('completed_with_errors' if any(e['status'] not in SUCCESS for e in entries) else 'completed')
        return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description='Convert a directory of KiCad footprints; errors remain isolated.')
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--limit', type=int, help='Convert only the first N source paths in stable order')
    parser.add_argument('--stl-root', type=Path, default=DEFAULT_STL_ROOT)
    parser.add_argument('--encoding', default='cp1251')
    parser.add_argument('--description-policy', choices=('preserve', 'ascii-escape-with-loss'), default='preserve',
                        help='Printable ASCII tokens for Unicode/quotes/controls in descriptions; pad labels and graphic text are unchanged')
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--curve-tolerance', type=float, default=0.01)
    parser.add_argument('--fill-tolerance', type=float, default=0.01)
    parser.add_argument('--default-mask-margin', type=float)
    parser.add_argument('--default-paste-margin', type=float)
    parser.add_argument('--default-paste-ratio', type=float)
    parser.add_argument('--model-translation', type=float, nargs=3)
    parser.add_argument('--model-rotation', type=float, nargs=3)
    parser.add_argument('--model-scale', type=float, nargs=3)
    parser.add_argument('--text-variable', action='append', default=[], metavar='NAME=VALUE')
    args = parser.parse_args()
    try:
        variables = {}
        for binding in args.text_variable:
            key, sep, value = binding.partition('=')
            if not sep or not key or key in variables:
                raise ConversionError('Text binding must be unique NAME=VALUE')
            variables[key] = value
        transform = None
        if any(v is not None for v in (args.model_translation, args.model_rotation, args.model_scale)):
            transform = ModelTransform(tuple(args.model_translation or ZERO),
                                       tuple(args.model_rotation or ZERO), tuple(args.model_scale or ONE))
        result = run_batch(args.input, args.output, resume=args.resume, limit=args.limit,
                           stl_root=args.stl_root, encoding=args.encoding, strict=args.strict,
                           description_policy=args.description_policy,
                           curve_tolerance=args.curve_tolerance, fill_tolerance=args.fill_tolerance,
                           text_variables=variables, model_transform=transform,
                           aperture_defaults=ApertureSettings(args.default_mask_margin,
                                                              args.default_paste_margin, args.default_paste_ratio))
    except (ValueError, OSError, LookupError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    counts = result['summary']
    print(f"Batch: {counts['total']} selected, {counts['generated']} generated "
          f"({counts['generated_with_loss']} with loss), {counts['reused']} reused, "
          f"{counts['failed']} failed, {counts['rejected_loss']} rejected by strict")
    print(f'Manifest: {args.output / "manifest.json"}')
    return 0 if result['status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
