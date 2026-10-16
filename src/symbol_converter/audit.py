"""Read-only completed symbol-batch audit; hashes and source/CDS pin endpoints."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from src.footprint_converter.audit import member, checked_bytes
from src.footprint_converter.batch import SUCCESS
from src.footprint_converter.io import atomic_write, validate_output_path
from src.footprint_converter.model_matching import DEFAULT_STL_ROOT
from . import parse_library
from .batch import summary
from .batch_records import verify_source_pins


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def audit_batch(source, batch, provenance=None):
    source, batch = Path(source).resolve(), Path(batch).resolve()
    manifest_raw = (batch / 'manifest.json').read_bytes()
    manifest = json.loads(manifest_raw)
    if manifest.get('kind') != 'symbol_batch' or manifest.get('schema_version') != 1 or manifest.get('status') not in {'completed', 'completed_with_errors'}:
        raise ValueError('Audit requires a completed symbol batch')
    entries, libraries = manifest['entries'], manifest['libraries']
    if (len(entries) != manifest['selected'] or len({(e['source'], e['symbol']) for e in entries}) != len(entries)
            or any(e['status'] not in SUCCESS | {'failed', 'rejected_loss'} for e in entries)
            or summary(entries, libraries) != manifest['summary']):
        raise ValueError('Invalid symbol batch inventory/summary')
    pinned = {}
    provenance_sha = None
    if provenance:
        raw = Path(provenance).read_bytes()
        p = json.loads(raw)
        provenance_sha = digest(raw)
        pinned = {item['file']: item for item in p['files']}
        if len(pinned) != len(p['files']) or set(pinned) != {r['source'] for r in libraries}:
            raise ValueError('Provenance/library inventory mismatch')
    by_library = {}
    for entry in entries:
        by_library.setdefault(entry['source'], []).append(entry)
    features = {k: Counter() for k in ('electrical_types', 'graphic_kinds', 'pin_styles', 'source_diagnostic_codes')}
    items, library_errors = [], []
    for record in libraries:
        raw = checked_bytes(member(source, record['source']), record['input_sha256'])
        if pinned:
            r = pinned[record['source']]
            blob = hashlib.sha1(f'blob {len(raw)}\0'.encode() + raw).hexdigest()
            if (r['bytes'], r['sha256'], r['git_blob_sha1']) != (len(raw), digest(raw), blob):
                raise ValueError('Pinned symbol source mismatch')
        library = None
        try:
            library = parse_library(raw.decode('utf-8-sig'))
        except (ValueError, OSError) as error:
            library_errors.append(dict(source=record['source'], error=str(error)))
        known = set(record['symbols'])
        if any(e['symbol'] not in known or e['input_sha256'] != record['input_sha256'] for e in by_library.get(record['source'], [])):
            raise ValueError('Source symbol identity mismatch')
        for entry in by_library.get(record['source'], []):
            item = dict(source=entry['source'], symbol=entry['symbol'], input_sha256=entry['input_sha256'],
                        status=entry['status'], source_pin_records_validated=False)
            if library is not None:
                symbol = library.get_symbol(entry['symbol'])
                pins = [pin for unit in symbol.units for pin in unit.pins]
                item.update(resolved_source_pin_records=len(pins), source_units=symbol.unit_count)
                features['electrical_types'].update(pin.electrical_type for pin in pins)
                features['pin_styles'].update(pin.graphic_style for pin in pins)
                features['graphic_kinds'].update(g.kind for unit in symbol.units for g in unit.graphics)
                features['source_diagnostic_codes'].update(d.code for d in symbol.diagnostics)
            report_raw = checked_bytes(member(batch, entry['report_file']), entry['report_sha256'])
            report = json.loads(report_raw)
            if report['status'] != entry['status']:
                raise ValueError('Symbol report/manifest status mismatch')
            if entry['status'] in SUCCESS:
                if library is None or entry['output_current'] is not True:
                    raise ValueError('Success has no source library/current artifact')
                cds = checked_bytes(member(batch, entry['output_file']), entry['output_sha256']).decode('cp1251')
                check = verify_source_pins(library, entry['symbol'], cds, report)
                if check != entry['readback'] or report['artifact_sha256'] != entry['output_sha256']:
                    raise ValueError('Source/CDS readback or report artifact mismatch')
                item.update(check, output_sha256=entry['output_sha256'])
            else:
                if entry['output_current'] is not False:
                    raise ValueError('Failed symbol incorrectly marked current')
                item.update(errors=entry['errors'], error_type=entry['error_type'],
                            unexpected_error=entry.get('unexpected_error', False), failure_category=entry['failure_category'])
            items.append(item)
    if len(items) != len(entries):
        raise ValueError('Audit did not account for every selected symbol')
    return dict(schema_version=1, kind='symbol_batch_audit', batch_manifest_sha256=digest(manifest_raw),
                source_provenance_sha256=provenance_sha, options=manifest['options'], summary=manifest['summary'],
                source_pin_records_validated=sum(i['source_pin_records_validated'] for i in items),
                target_gui_validated=False, native_netlist_verified=False, physical_footprint_mapping_verified=False,
                source_features={key: dict(sorted(value.items())) for key, value in features.items()},
                library_errors=library_errors, items=items)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('batch', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--provenance', type=Path)
    args = parser.parse_args(argv)
    try:
        validate_output_path(args.output, args.input, DEFAULT_STL_ROOT)
        if (args.output.resolve().is_relative_to(args.input.resolve()) or args.output.resolve().is_relative_to(args.batch.resolve())
                or args.output.suffix != '.json' or args.provenance and args.output.resolve() == args.provenance.resolve()):
            raise ValueError('Audit JSON must be outside source/batch and differ from provenance')
        result = audit_batch(args.input, args.batch, args.provenance)
        atomic_write(args.output, (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode())
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('Symbol audit failed: ' + str(error), file=sys.stderr)
        return 1
    print(f"Symbol audit: {result['source_pin_records_validated']} CDS checked, {result['summary']['failed']} refused; native validation pending")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
