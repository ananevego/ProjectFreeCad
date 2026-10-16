"""Exact fixed-footprint candidates between two audited batches; no assignment.

Only literal source identifiers and unique native pin/pad number sets are used.
Wildcards, missing footprints and repeated pad labels remain unresolved.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

from src.footprint_converter.audit import member, checked_bytes, read_pads
from src.footprint_converter.batch import SUCCESS
from src.footprint_converter.io import atomic_write, validate_output_path
from src.footprint_converter.model_matching import DEFAULT_STL_ROOT
from src.symbol_converter.schemator_format import parse_cds


def load_audited(batch, audit_path, kind):
    raw = (batch / 'manifest.json').read_bytes()
    manifest = json.loads(raw)
    audit_raw = audit_path.read_bytes()
    audit = json.loads(audit_raw)
    if (manifest.get('kind') != kind + '_batch' or audit.get('kind') != kind + '_batch_audit'
            or manifest.get('status') not in {'completed', 'completed_with_errors'}
            or audit.get('batch_manifest_sha256') != hashlib.sha256(raw).hexdigest()):
        raise ValueError('Component inventory requires matching completed batch audits')
    return manifest, audit, hashlib.sha256(audit_raw).hexdigest()


def inventory_links(symbol_batch, symbol_audit, footprint_batch, footprint_audit):
    symbol_batch, symbol_audit, footprint_batch, footprint_audit = map(Path, (symbol_batch, symbol_audit, footprint_batch, footprint_audit))
    sm, sa, symbol_audit_sha = load_audited(symbol_batch, symbol_audit, 'symbol')
    fm, fa, footprint_audit_sha = load_audited(footprint_batch, footprint_audit, 'footprint')
    footprints = {e['source']: e for e in fm['entries']}
    audited_footprints = {e['source']: e for e in fa['items']}
    if len(footprints) != len(fm['entries']) or set(footprints) != set(audited_footprints):
        raise ValueError('Footprint audit inventory mismatch')
    cache, items = {}, []
    for entry in sm['entries']:
        item = dict(source=entry['source'], symbol=entry['symbol'], literal_number_mapping_verified=False,
                    cds_footprint_assigned=False, native_netlist_verified=False)
        if entry['status'] not in SUCCESS:
            item['status'] = 'symbol_refused'
            items.append(item)
            continue
        raw = checked_bytes(member(symbol_batch, entry['report_file']), entry['report_sha256'])
        report = json.loads(raw)
        identifier = report['source_symbol']['properties']['Footprint']['value']
        item['source_footprint_identifier'] = identifier
        if not identifier:
            item['status'] = 'footprint_unspecified'
        elif (len(identifier.split(':')) != 2 or any(c in identifier for c in '*?[]/\\')
              or any(not p or p in {'.', '..'} for p in identifier.split(':'))):
            item['status'] = 'footprint_identifier_not_literal'
        else:
            category, name = identifier.split(':')
            relative = category + '.pretty/' + name + '.kicad_mod'
            item['footprint_source'] = relative
            footprint = footprints.get(relative)
            if footprint is None:
                item['status'] = 'footprint_absent'
            elif footprint['status'] not in SUCCESS:
                item['status'] = 'footprint_refused'
            else:
                if relative not in cache:
                    audit = audited_footprints[relative]
                    if (audit['output_sha256'] != footprint['output_sha256'] or not audit['target_records_validated']
                            or footprint['output_current'] is not True):
                        raise ValueError('Footprint candidate is not current/audited')
                    raw = checked_bytes(member(footprint_batch, footprint['output_file']), footprint['output_sha256'])
                    _, pads = read_pads(raw.decode(fm['options']['encoding']))
                    numbers = [pad['name'] for pad in pads if any(pad['records'].get(side + '_pad', [0])[0]
                               for side in ('top', 'bottom', 'inner'))]
                    cache[relative] = numbers
                pads = cache[relative]
                if len(set(pads)) != len(pads):
                    item['status'] = 'footprint_numbers_ambiguous'
                else:
                    raw = checked_bytes(member(symbol_batch, entry['output_file']), entry['output_sha256'])
                    doc = parse_cds(raw.decode('cp1251'))
                    numbers = [poly.pin.value for poly in doc.components[0].polylines if poly.pin]
                    if doc.components[0].footprint.value != 'PART':
                        raise ValueError('Unlinked symbol batch no longer has PART placeholders')
                    if sorted(numbers) != sorted(pads):
                        item.update(status='pin_pad_numbers_differ', symbol_numbers=sorted(numbers), pad_numbers=sorted(pads))
                    else:
                        item.update(status='eligible_for_linked_export', literal_number_mapping_verified=True,
                                    footprint_target_name=footprint['target_name'], physical_numbers=sorted(numbers),
                                    matched_external_models=audited_footprints[relative]['matched_models'])
        items.append(item)
    counts = dict(sorted(Counter(i['status'] for i in items).items()))
    return dict(schema_version=1, kind='audited_component_candidates', symbol_audit_sha256=symbol_audit_sha,
                footprint_audit_sha256=footprint_audit_sha, target_gui_validated=False,
                native_netlist_verified=False, model_alignment_validated=False,
                cds_footprints_assigned=False, summary=dict(total=len(items), statuses=counts,
                    eligible_with_existing_model=sum(i['status'] == 'eligible_for_linked_export' and i['matched_external_models'] > 0 for i in items)),
                scope='Literal fixed footprint identifier and unique CDS/copper-pad number equality; no guesses, assignments, mesh reads or native verification',
                items=items)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('symbol_batch', 'symbol_audit', 'footprint_batch', 'footprint_audit', 'output'):
        parser.add_argument(name, type=Path)
    args = parser.parse_args(argv)
    try:
        validate_output_path(args.output, args.symbol_audit, DEFAULT_STL_ROOT)
        if (args.output.suffix != '.json' or any(args.output.resolve().is_relative_to(root.resolve()) for root in (args.symbol_batch, args.footprint_batch))
                or args.output.resolve() == args.footprint_audit.resolve()):
            raise ValueError('Candidate JSON must be outside batches and differ from audits')
        result = inventory_links(args.symbol_batch, args.symbol_audit, args.footprint_batch, args.footprint_audit)
        atomic_write(args.output, (json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode())
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('Component candidate inventory failed: ' + str(error), file=sys.stderr)
        return 1
    print(json.dumps(result['summary'], sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
