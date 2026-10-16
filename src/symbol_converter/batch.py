"""Deterministic modern KiCad symbol batches; one CDS/report per source symbol."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys

from src.footprint_converter.batch import batch_lock, validate_destination, SUCCESS
from src.footprint_converter.io import atomic_write, validate_output_path
from src.footprint_converter.model_matching import DEFAULT_STL_ROOT
from src.footprint_converter.parser import parse_sexpr
from . import parse_library
from .batch_records import verify_source_pins
from .body_graphics import validate_fill_tolerance
from .curves import validate_tolerance
from .model import SymbolParseError
from .multiunit import validate_unit_gap, validate_common_pin_policy
from .pin_policy import validate_no_connect_policy
from .pin_graphics import validate_hidden_policy
from .target import convert_symbol, LossySymbolConversionError
from .pin_labels import validate_pin_name_policy, validate_alternate_pin_policy


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()


def engine_fingerprint():
    root = Path(__file__).parent
    files = sorted([*root.glob('*.py'), *(root.parent / 'footprint_converter').glob('*.py')])
    return digest(b''.join(p.parent.name.encode() + b'/' + p.name.encode() + b'\0' + p.read_bytes() for p in files))


def item_name(source, symbol):
    key = json.dumps([source, symbol], ensure_ascii=False, separators=(',', ':'))
    label = re.sub(r'[^A-Za-z0-9_.-]+', '_', Path(source).stem + '_' + symbol).strip('._-')
    return 'sy_' + label[:60] + '_' + digest(key.encode())[:16]


def inventory(source):
    files = []
    def walk_error(error):
        raise error
    for folder, directories, names in os.walk(source, followlinks=False, onerror=walk_error):
        directories[:] = sorted(n for n in directories if not (Path(folder) / n).is_symlink())
        files.extend(Path(folder) / n for n in names if n.endswith('.kicad_sym'))
    libraries = []
    for path in sorted(files, key=lambda p: p.relative_to(source).as_posix()):
        record = dict(source=path.relative_to(source).as_posix(), symbols=[])
        try:
            if path.is_symlink():
                raise SymbolParseError('Symlink source library is unsupported')
            raw = path.read_bytes()
            record.update(input_sha256=digest(raw), bytes=len(raw))
            tree = parse_sexpr(raw.decode('utf-8-sig'))
            if not tree or tree[0] != 'kicad_symbol_lib':
                raise SymbolParseError('Expected modern KiCad symbol library')
            names = [node[1] for node in tree[1:] if isinstance(node, list) and node and node[0] == 'symbol']
            if any(not isinstance(n, str) or not n for n in names) or len(set(names)) != len(names):
                raise SymbolParseError('Empty/duplicate source symbol identifier')
            record['symbols'] = sorted(names)
        except (OSError, ValueError, IndexError) as error:
            record['inventory_error'] = str(error)
        libraries.append(record)
    return libraries


def failure_category(message):
    for part, category in [('source diagnostics', 'SOURCE_DIAGNOSTICS'),
                           ('standard body style', 'ALTERNATE_BODY_STYLE'),
                           ('Power/virtual/BOM-excluded', 'VIRTUAL_OR_EXCLUDED_SYMBOL'),
                           ('disjoint; repeated', 'REPEATED_PHYSICAL_PIN_NUMBERS'),
                           ('shared-pin policy', 'COMMON_PINS_REQUIRE_POLICY'),
                           ('hidden pin requires', 'HIDDEN_PIN_REQUIRES_POLICY'),
                           ('no-connect cannot', 'NO_CONNECT_REQUIRES_POLICY'),
                           ('alternate pin', 'ALTERNATE_PIN_MODE'),
                           ('ambiguous/unsupported native number', 'NATIVE_PIN_IDENTIFIER'),
                           ('CP1251', 'TARGET_TEXT_UNREPRESENTABLE'),
                           ('Unrepresentable CDS string', 'TARGET_TEXT_UNREPRESENTABLE'),
                           ('markup', 'TARGET_TEXT_MARKUP'),
                           ('Filled', 'BODY_FILL_OUTSIDE_PROFILE'),
                           ('outside', 'TARGET_PROFILE_LIMIT'),
                           ('requires at least one physical pin', 'NO_PHYSICAL_PINS')]:
        if part in message:
            return category
    return 'TARGET_PROFILE_REFUSAL'


def summary(entries, libraries):
    counts = Counter(e['status'] for e in entries)
    return dict(total=len(entries), generated=sum(counts[s] for s in SUCCESS),
                generated_with_loss=counts['generated_with_loss'], failed=counts['failed'],
                rejected_loss=counts['rejected_loss'], pending=counts['pending'],
                reused=sum(e.get('reused', False) for e in entries),
                source_libraries=len(libraries), inventory_failed_libraries=sum('inventory_error' in r for r in libraries),
                source_inventory_complete=not any('inventory_error' in r for r in libraries),
                unexpected_errors=sum(e.get('unexpected_error', False) for e in entries),
                written_pin_records=sum(e.get('readback', {}).get('pins', 0) for e in entries if e['status'] in SUCCESS),
                diagnostic_item_counts=dict(sorted(Counter(d['code'] for e in entries for d in e.get('diagnostics', [])).items())),
                first_failure_categories=dict(sorted(Counter(e['failure_category'] for e in entries if 'failure_category' in e).items())))


def read_json(path):
    try:
        result = json.loads(path.read_bytes())
        return result if isinstance(result, dict) else None
    except (OSError, ValueError):
        return None


def valid_cache(value):
    if not isinstance(value, dict) or not isinstance(value.get('status'), str) or value['status'] not in SUCCESS:
        return False
    diagnostics, readback = value.get('diagnostics'), value.get('readback')
    return (value.get('output_current') is True and isinstance(diagnostics, list)
            and all(isinstance(d, dict) and all(isinstance(d.get(k), str) for k in ('code', 'severity')) for d in diagnostics)
            and isinstance(readback, dict) and type(readback.get('pins')) is int and readback['pins'] >= 0
            and readback.get('source_pin_records_validated') is True
            and all(isinstance(value.get(k), str) and re.fullmatch('[0-9a-f]{64}', value[k])
                    for k in ('output_sha256', 'report_sha256')))


def run_batch(input_dir, output_dir, *, resume=False, limit=None, strict=False,
              default_line_width=.254, pin_width=.254, curve_tolerance=.01, fill_tolerance=.01,
              unit_gap=2.54, no_connect_policy='reject', hidden_pin_policy='reject', common_pin_policy='reject',
              pin_name_policy='reject', alternate_pin_policy='reject'):
    source, output = Path(input_dir).resolve(), Path(output_dir).resolve()
    if not source.is_dir() or output.is_relative_to(source) or source.is_relative_to(output):
        raise SymbolParseError('Existing source and output directories must be disjoint')
    validate_output_path(output, source, DEFAULT_STL_ROOT)
    if limit is not None and (type(limit) is not int or limit <= 0):
        raise SymbolParseError('Symbol limit must be a positive integer')
    validate_tolerance(curve_tolerance)
    validate_fill_tolerance(fill_tolerance)
    validate_unit_gap(unit_gap)
    validate_no_connect_policy(no_connect_policy)
    validate_hidden_policy(hidden_pin_policy)
    validate_common_pin_policy(common_pin_policy)
    validate_pin_name_policy(pin_name_policy)
    validate_alternate_pin_policy(alternate_pin_policy)
    if any(type(n) not in (int, float) or not math.isfinite(n) or not 0 < n <= 2147.483647 or round(n * 1e6) <= 0
           for n in (default_line_width, pin_width)):
        raise SymbolParseError('Line/pin widths must be positive native dimensions')
    options = dict(strict=strict, default_line_width=default_line_width, pin_width=pin_width,
                   curve_tolerance=curve_tolerance, fill_tolerance=fill_tolerance, unit_gap=unit_gap,
                   no_connect_policy=no_connect_policy, hidden_pin_policy=hidden_pin_policy,
                   common_pin_policy=common_pin_policy, pin_name_policy=pin_name_policy,
                   alternate_pin_policy=alternate_pin_policy)
    fingerprint = digest(json_bytes(dict(options=options, engine=engine_fingerprint())))
    libraries = inventory(source)
    if not libraries:
        raise SymbolParseError('No .kicad_sym libraries found')
    entries = []
    for library in libraries:
        for name in library['symbols']:
            target = item_name(library['source'], name)
            entries.append(dict(source=library['source'], symbol=name, input_sha256=library['input_sha256'],
                                target_name=target, output_file='symbols/' + target + '.cds',
                                report_file='reports/' + target + '.report.json', state_file='state/' + target + '.json',
                                status='pending', output_current=False, reused=False))
    discovered = len(entries)
    if limit:
        entries = entries[:limit]
    if len({e['target_name'].casefold() for e in entries}) != len(entries):
        raise SymbolParseError('Batch target naming collision')
    manifest_path, lock = output / 'manifest.json', output / '.batch.lock'
    for path in [manifest_path, lock] + [output / e[key] for e in entries for key in ('output_file', 'report_file', 'state_file')]:
        validate_destination(path, output, source, DEFAULT_STL_ROOT)
    output.mkdir(parents=True, exist_ok=True)
    with batch_lock(lock):
        previous = read_json(manifest_path)
        if manifest_path.exists() and (not previous or previous.get('kind') != 'symbol_batch'
                or previous.get('schema_version') != 1 or previous.get('input_root') != str(source)
                or not isinstance(previous.get('artifact_owners'), dict)):
            raise SymbolParseError('Existing symbol manifest is invalid or belongs to another source')
        owners = dict(previous.get('artifact_owners', {})) if previous else {}
        for entry in entries:
            old = owners.get(entry['target_name'], {})
            if not isinstance(old, dict):
                raise SymbolParseError('Invalid symbol artifact ownership record')
            for key in ('output_file', 'report_file', 'state_file'):
                if (output / entry[key]).exists() and (old.get('source'), old.get('symbol'), old.get(key)) != (entry['source'], entry['symbol'], entry[key]):
                    raise SymbolParseError('Refusing to replace an unowned symbol artifact')
            owners[entry['target_name']] = {k: entry[k] for k in ('source', 'symbol', 'output_file', 'report_file', 'state_file')}
        manifest = dict(schema_version=1, kind='symbol_batch', status='running', input_root=str(source),
                        output_root=str(output), configuration_fingerprint=fingerprint, options=options,
                        libraries=libraries, discovered=discovered, selected=len(entries), limit=limit,
                        entries=entries, artifact_owners=owners, target_gui_validated=False,
                        native_netlist_verified=False, physical_footprint_mapping_verified=False)
        def checkpoint(status='running'):
            manifest.update(status=status, summary=summary(entries, libraries))
            atomic_write(manifest_path, json_bytes(manifest))
        checkpoint()
        grouped = defaultdict(list)
        for entry in entries:
            grouped[entry['source']].append(entry)
        processed, next_checkpoint = 0, 50
        for relative, group in grouped.items():
            library = None
            library_error = None
            for entry in group:
                report = None
                try:
                    state_path, report_path, destination = (output / entry[k] for k in ('state_file', 'report_file', 'output_file'))
                    cached = read_json(state_path) if resume else None
                    identity = ('source', 'symbol', 'input_sha256', 'target_name', 'output_file', 'report_file', 'state_file')
                    if (valid_cache(cached) and cached.get('configuration_fingerprint') == fingerprint
                            and cached.get('input_root') == str(source)
                            and all(cached.get(k) == entry[k] for k in identity)
                            and destination.is_file() and report_path.is_file()
                            and digest(destination.read_bytes()) == cached.get('output_sha256')
                            and digest(report_path.read_bytes()) == cached.get('report_sha256')):
                        entry.update(cached, reused=True)
                    else:
                        if library is None and library_error is None:
                            try:
                                path = source / relative
                                if path.is_symlink():
                                    raise SymbolParseError('Symlink source library is unsupported')
                                raw = path.read_bytes()
                                if digest(raw) != entry['input_sha256']:
                                    raise SymbolParseError('Source library changed during the batch')
                                library = parse_library(raw.decode('utf-8-sig'))
                            except Exception as error:
                                library_error = error
                        if library_error is not None:
                            raise library_error
                        result = convert_symbol(library, entry['symbol'], project_name=destination.name, **options)
                        raw = result.cds.encode('cp1251')
                        readback = verify_source_pins(library, entry['symbol'], result.cds, result.report)
                        report = dict(result.report, source=dict(library=relative, symbol=entry['symbol'], sha256=entry['input_sha256']))
                        atomic_write(destination, raw)
                        unique = {(d['code'], d['severity']) for d in result.report['diagnostics']}
                        entry.update(status=result.report['status'], output_current=True, output_sha256=digest(raw),
                                     readback=readback, diagnostics=[dict(code=c, severity=s) for c, s in sorted(unique)])
                except Exception as error:
                    report = dict(error.report) if isinstance(error, LossySymbolConversionError) else dict(status='failed')
                    entry.update(status=report['status'], output_current=False, reused=False, errors=[str(error)],
                                 error_type=type(error).__name__, unexpected_error=not isinstance(error, (ValueError, OSError)),
                                 failure_stage='source_library' if library_error is not None else 'target',
                                 failure_category='STRICT_LOSS' if isinstance(error, LossySymbolConversionError) else failure_category(str(error)))
                    entry.pop('output_sha256', None)
                    report.update(errors=entry['errors'], error_type=entry['error_type'], unexpected_error=entry['unexpected_error'])
                if report is not None:
                    try:
                        encoded = json_bytes(report)
                        atomic_write(output / entry['report_file'], encoded)
                        entry['report_sha256'] = digest(encoded)
                        atomic_write(output / entry['state_file'], json_bytes(dict(entry, input_root=str(source), configuration_fingerprint=fingerprint)))
                    except OSError as error:
                        entry.update(status='failed', output_current=False, reused=False,
                                     failure_category='ARTIFACT_WRITE_FAILED', error_type=type(error).__name__,
                                     errors=entry.get('errors', []) + [str(error)], unexpected_error=False)
                        entry.pop('output_sha256', None)
                processed += 1
                if processed == next_checkpoint:
                    checkpoint()
                    next_checkpoint *= 2
        checkpoint('completed_with_errors' if any(e['status'] not in SUCCESS for e in entries)
                   or any('inventory_error' in r for r in libraries) else 'completed')
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--curve-tolerance', type=float, default=.01)
    parser.add_argument('--fill-tolerance', type=float, default=.01)
    parser.add_argument('--unit-gap', type=float, default=2.54)
    parser.add_argument('--no-connect-policy', choices=('reject', 'connectable-with-loss'), default='reject')
    parser.add_argument('--hidden-pin-policy', choices=('reject', 'reveal-with-loss'), default='reject')
    parser.add_argument('--common-pin-policy', choices=('reject', 'common-view-with-loss'), default='reject')
    parser.add_argument('--pin-name-policy', choices=('reject', 'plain-overbar-with-loss'), default='reject')
    parser.add_argument('--alternate-pin-policy', choices=('reject', 'primary-with-loss'), default='reject')
    args = parser.parse_args(argv)
    try:
        result = run_batch(args.input, args.output, resume=args.resume, limit=args.limit, strict=args.strict,
                           curve_tolerance=args.curve_tolerance, fill_tolerance=args.fill_tolerance, unit_gap=args.unit_gap,
                           no_connect_policy=args.no_connect_policy, hidden_pin_policy=args.hidden_pin_policy,
                           common_pin_policy=args.common_pin_policy, pin_name_policy=args.pin_name_policy,
                           alternate_pin_policy=args.alternate_pin_policy)
    except (ValueError, OSError) as error:
        print('Symbol batch failed: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result['summary'], sort_keys=True))
    return 0 if result['status'] == 'completed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
