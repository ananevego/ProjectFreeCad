"""Export linked libraries and byte-preserved existing STL snapshots.

The package contains relative paths only for generated assets. A flat model
folder serves FreePCB2's basename imports; the category tree is also retained.
No meshes are interpreted and no native GUI/netlist validation is implied.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile

from src.footprint_converter.io import validate_output_path
from src.footprint_converter.model import ApertureSettings, ModelTransform
from src.footprint_converter.model_matching import DEFAULT_STL_ROOT, match_models
from src.footprint_converter.parser import parse_sexpr, parse_footprint
from src.footprint_converter.pipeline import convert_detailed
from src.footprint_converter.errors import LossyConversionError
from src.symbol_converter import parse_library
from src.symbol_converter.schemator_format import parse_cds
from src.symbol_converter.target import convert_symbol, LossySymbolConversionError
from src.symbol_converter.curves import validate_tolerance, DEFAULT_CURVE_TOLERANCE
from src.symbol_converter.body_graphics import validate_fill_tolerance, DEFAULT_FILL_TOLERANCE
from src.symbol_converter.multiunit import validate_unit_gap, DEFAULT_UNIT_GAP, validate_common_pin_policy
from src.symbol_converter.pin_policy import validate_no_connect_policy
from src.symbol_converter.pin_labels import validate_pin_name_policy, validate_alternate_pin_policy
from src.symbol_converter.pin_graphics import validate_hidden_policy
from .links import LinkError, footprint_identifier, pin_mapping, stable_name
from .records import read_fpl_links

RUNTIME_FOLDER = 'openscad_models/Bundle.3dshapes'
SUCCESS = {'generated', 'generated_with_loss'}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024*1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)+'\n').encode('utf-8')


def _unique_pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f'Duplicate JSON key: {key}')
        value[key] = item
    return value


def _invalid_constant(value):
    raise ValueError(f'Non-finite JSON constant: {value}')


def load_config(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    config = json.loads(data.decode('utf-8-sig'), object_pairs_hook=_unique_pairs,
                        parse_constant=_invalid_constant)
    if not isinstance(config, dict) or set(config) - {
            'schema_version', 'footprint_libraries', 'components', 'aperture_defaults', 'symbol_curve_tolerance', 'symbol_fill_tolerance', 'symbol_unit_gap', 'symbol_no_connect_policy', 'symbol_hidden_pin_policy', 'symbol_common_pin_policy', 'symbol_pin_name_policy', 'symbol_alternate_pin_policy'}:
        raise ValueError('Unknown/invalid component config fields')
    if type(config.get('schema_version')) is not int or config['schema_version'] != 1:
        raise ValueError('Expected component config schema_version 1')
    libraries, components = config.get('footprint_libraries'), config.get('components')
    if not isinstance(libraries, dict) or not libraries or not isinstance(components, list) or not components:
        raise ValueError('Nonempty footprint_libraries/components required')
    for name, directory in libraries.items():
        footprint_identifier(name+':example')
        if not isinstance(directory, str) or not directory.strip():
            raise ValueError('Footprint library directory must be a nonempty path')
    ids = set()
    for component in components:
        if not isinstance(component, dict) or set(component) - {
                'id', 'symbol_library', 'symbol', 'footprint', 'reference', 'model_transform'}:
            raise ValueError('Unknown/invalid component fields')
        for key in ('id', 'symbol_library', 'symbol'):
            if not isinstance(component.get(key), str) or not component[key].strip():
                raise ValueError(f'Component requires {key}')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', component['id']) or component['id'].endswith('.'):
            raise ValueError('Component id must be a portable ASCII identifier')
        if component['id'].casefold() in ids:
            raise ValueError('Component ids must be unique including Windows case folding')
        ids.add(component['id'].casefold())
        for key in ('footprint', 'reference'):
            if key in component and not isinstance(component[key], str):
                raise ValueError(f'{key} must be a string')
        _transform(component.get('model_transform'))
    aperture = config.get('aperture_defaults', {})
    validate_tolerance(config.get('symbol_curve_tolerance',DEFAULT_CURVE_TOLERANCE))
    validate_fill_tolerance(config.get('symbol_fill_tolerance',DEFAULT_FILL_TOLERANCE))
    validate_unit_gap(config.get('symbol_unit_gap',DEFAULT_UNIT_GAP))
    validate_no_connect_policy(config.get('symbol_no_connect_policy','reject'))
    validate_hidden_policy(config.get('symbol_hidden_pin_policy','reject'))
    validate_common_pin_policy(config.get('symbol_common_pin_policy','reject'))
    validate_pin_name_policy(config.get('symbol_pin_name_policy','reject'))
    validate_alternate_pin_policy(config.get('symbol_alternate_pin_policy','reject'))
    if not isinstance(aperture, dict) or set(aperture) - {'mask_margin', 'paste_margin', 'paste_ratio'} or any(
            value is not None and (type(value) not in (float, int) or not math.isfinite(value))
            for value in aperture.values()):
        raise ValueError('Invalid aperture defaults')
    return config, data


def _transform(value) -> ModelTransform | None:
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'translation', 'rotation', 'scale'} or any(
            not isinstance(v, list) or len(v) != 3 or any(
                type(n) not in (int, float) or not math.isfinite(n) for n in v)
            for v in value.values()) or 0 in value['scale']:
        raise ValueError('Explicit model_transform requires three finite vectors; scale cannot contain zero')
    return ModelTransform(**{key: tuple(v) for key, v in value.items()})


def _portable_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or '\\' in relative:
        raise ValueError('Invalid bundle relative path')
    parts = PurePosixPath(relative)
    if parts.is_absolute() or not parts.parts or any(
            part in ('.', '..') or ':' in part for part in parts.parts) or parts.as_posix() != relative:
        raise ValueError('Unsafe bundle relative path')
    path = root.joinpath(*parts.parts)
    if any(parent.is_symlink() for parent in (path, *path.parents) if parent.is_relative_to(root)):
        raise ValueError('Bundle paths cannot contain symlinks')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Bundle artifact escapes its root')
    return path


def _source_segment(segment: str) -> None:
    device = segment.split('.')[0].upper()
    if segment != segment.strip() or segment.endswith('.') or device in {
            'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1,10)), *(f'LPT{i}' for i in range(1,10))} or any(
            c in '<>:"/\\|?*' or ord(c) < 32 for c in segment):
        raise LinkError('ambiguous', 'MODEL_PATH_NOT_PORTABLE', 'Model category/basename is not Windows-safe')


def _signature(path: Path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_ino


class Assets:
    def __init__(self, stage: Path):
        self.stage, self.records, self.case_names = stage, {}, {}

    def add(self, match) -> dict:
        relative = match.relative_path.as_posix()
        for part in match.relative_path.parts:
            _source_segment(part)
        if relative.casefold() in self.case_names and self.case_names[relative.casefold()] != relative:
            raise LinkError('ambiguous', 'MODEL_CASE_COLLISION', 'Model paths collide on Windows')
        self.case_names[relative.casefold()] = relative
        if relative in self.records:
            record, signature = self.records[relative]
            if _signature(match.stl_path) != signature:
                raise LinkError('failed', 'MODEL_CHANGED', 'Existing model changed during bundle construction')
            return record
        signature = _signature(match.stl_path)
        canonical = 'models/'+relative
        alias = stable_name(relative.removesuffix('.stl'), 'mdl')+'.stl'
        runtime = RUNTIME_FOLDER+'/'+alias
        target = _portable_path(self.stage, canonical)
        target.parent.mkdir(parents=True, exist_ok=True)
        hasher, size = hashlib.sha256(), 0
        with match.stl_path.open('rb') as source, target.open('xb') as output:
            for block in iter(lambda: source.read(1024*1024), b''):
                hasher.update(block)
                size += len(block)
                output.write(block)
        if size == 0 or _signature(match.stl_path) != signature or size != signature[0]:
            raise LinkError('failed', 'MODEL_CHANGED', 'Model was empty or changed while copying')
        runtime_path = _portable_path(self.stage, runtime)
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(target, runtime_path)
        record = dict(source_relative=relative, canonical_path=canonical, runtime_path=runtime,
                      import_basename=alias, bytes=size, sha256=hasher.hexdigest(), frame_validated=False)
        self.records[relative] = record, signature
        return record

    def retain(self, used: set[str]) -> list[dict]:
        records = []
        for relative, (record, _) in sorted(self.records.items()):
            if relative in used:
                records.append(record)
            else:
                for key in ('canonical_path', 'runtime_path'):
                    _portable_path(self.stage, record[key]).unlink()
        # Remove unregistered partial copies after an item failed while copying.
        allowed = {r[key] for r in records for key in ('canonical_path', 'runtime_path')}
        for directory in ('models', 'openscad_models'):
            for path in (self.stage/directory).rglob('*'):
                if path.is_file() and path.relative_to(self.stage).as_posix() not in allowed:
                    path.unlink()
        return records

    def rollback(self, checkpoint: set[str]) -> None:
        self.retain(checkpoint)
        self.records = {key: value for key, value in self.records.items() if key in checkpoint}
        self.case_names = {key.casefold(): key for key in self.records}


def _check_records(cds: str, fpl: str, expected_name: str, mapping: dict, models: list[dict]) -> None:
    doc, footprint = parse_cds(cds), read_fpl_links(fpl)
    if len(doc.components) != 1:
        raise ValueError('Expected one CDS component')
    symbol = doc.components[0]
    numbers = sorted(poly.pin.value for poly in symbol.polylines if poly.pin)
    if (symbol.footprint.value != expected_name or footprint['name'] != expected_name or
            numbers != mapping['source_numbers'] or footprint['numbers'] != mapping['pad_numbers'] or
            numbers != footprint['numbers'] or not mapping['verified'] or
            footprint['mechanical_pads'] != mapping['mechanical_pads']):
        raise ValueError('Source/CDS/FPL number or footprint-name correspondence failed')
    if sorted(footprint['imports']) != sorted(m['import_basename'] for m in models):
        raise ValueError('FPL imports do not match the selected bundled models')


def _convert_item(component: dict, config: dict, base: Path, stage: Path,
                  assets: Assets, stl_root: Path, cache: dict, allow_missing: bool, strict: bool) -> dict:
    entry = dict(id=component['id'], status='failed', source_target_mapping_verified=False,
                 chain_complete=False, native_import_verified=False, gui_validated=False)
    folder = 'components/'+stable_name(component['id'], 'c')
    entry['report'] = folder+'/report.json'
    checkpoint = set(assets.records)
    try:
        library_path = (base/component['symbol_library']).resolve()
        if library_path.suffix.lower() not in ('.lib', '.kicad_sym'):
            raise ValueError('Unsupported symbol library extension')
        if library_path not in cache:
            data = library_path.read_bytes()
            cache[library_path] = parse_library(data.decode('utf-8-sig')), digest(data)
        library, library_hash = cache[library_path]
        if component['symbol'] not in library.symbols and component['symbol'] not in library.aliases:
            raise LinkError('unresolved', 'SYMBOL_MISSING', 'Exact symbol name not found')
        symbol = library.get_symbol(component['symbol'])
        source_id = symbol.properties.get('Footprint')
        source_id = source_id.value if source_id else ''
        selected = component.get('footprint', source_id)
        library_name, footprint_name = footprint_identifier(selected)
        if library_name not in config['footprint_libraries']:
            raise LinkError('unresolved', 'FOOTPRINT_LIBRARY_MISSING', 'Exact footprint namespace is not configured')
        footprint_path = (base/config['footprint_libraries'][library_name]/(footprint_name+'.kicad_mod')).resolve()
        data = footprint_path.read_bytes()
        root = parse_sexpr(data.decode('utf-8-sig'))
        if len(root) < 2 or root[1] != footprint_name:
            raise LinkError('unresolved', 'FOOTPRINT_NAME_MISMATCH', 'Identifier and source footprint root name differ')
        fp = parse_footprint(root)
        mapping = pin_mapping(symbol, fp)
        entry.update(pin_mapping=mapping, source=dict(symbol_library=component['symbol_library'],
            symbol=component['symbol'], symbol_library_sha256=library_hash,
            footprint_identifier=selected, footprint_sha256=digest(data),
            source_footprint_property=source_id, selection='explicit_config' if 'footprint' in component else 'source_property'))
        if not mapping['verified']:
            raise LinkError('ambiguous' if mapping['status']=='ambiguous' else 'unresolved',
                            'PIN_PAD_AMBIGUOUS' if mapping['status']=='ambiguous' else 'PIN_PAD_MISMATCH',
                            'Physical source pin/pad numbers do not form an unambiguous identity mapping')
        target_name = stable_name(selected)
        symbol_result = convert_symbol(library, component['symbol'], footprint_name=target_name,
            reference=component.get('reference'), project_name='symbol.cds',
            curve_tolerance=config.get('symbol_curve_tolerance',DEFAULT_CURVE_TOLERANCE),
            fill_tolerance=config.get('symbol_fill_tolerance',DEFAULT_FILL_TOLERANCE),
            unit_gap=config.get('symbol_unit_gap',DEFAULT_UNIT_GAP),
            no_connect_policy=config.get('symbol_no_connect_policy','reject'),
            hidden_pin_policy=config.get('symbol_hidden_pin_policy','reject'),
            common_pin_policy=config.get('symbol_common_pin_policy','reject'),
            pin_name_policy=config.get('symbol_pin_name_policy','reject'),
            alternate_pin_policy=config.get('symbol_alternate_pin_policy','reject'),strict=strict)
        visible_references = set(ref.path for ref in fp.models)
        matches, resolutions = [], []
        for ref in fp.models:
            warnings = []
            found = match_models([ref], stl_root, warnings)
            resolutions.extend(warnings)
            matches.extend(found)
        if not fp.models:
            resolutions.append('MODEL_MISSING: no visible source model reference')
        missing = bool(resolutions)
        entry.update(model_resolution_diagnostics=resolutions,
                     source_model_references=[asdict(ref) for ref in fp.models])
        if missing and not allow_missing:
            raise LinkError('unresolved', 'MODEL_LINK_UNRESOLVED', 'Required existing model reference is missing/unresolved')
        selected_models = [assets.add(match) for match in matches]
        aliases = {match.reference.path: model['import_basename'] for match, model in zip(matches, selected_models)}
        # Rewrite a COPY of the model references only. Geometry/transforms are
        # untouched; the originals and original source hash remain in reports.
        rewritten = deepcopy(root)
        rewritten[:] = [node for node in rewritten if not (
            isinstance(node, list) and node and node[0]=='model' and node[1] in visible_references and node[1] not in aliases)]
        for node in rewritten:
            if isinstance(node, list) and node and node[0]=='model' and node[1] in aliases:
                node[1] = 'Bundle.3dshapes/'+aliases[node[1]]
        fp_result = convert_detailed(rewritten, target_name, stl_root=stage/'openscad_models',
            model_transform=_transform(component.get('model_transform')),
            aperture_defaults=ApertureSettings(**config.get('aperture_defaults', {})), strict=strict)
        # Match deduplication in the existing converter also deduplicates exact
        # repeated model references. Retain the actual emitted import sequence.
        original_by_alias = {(aliases[m.reference.path], m.reference.offset, m.reference.rotation, m.reference.scale):
                             m.reference for m in matches}
        assets_by_alias = {m['import_basename']: m for m in selected_models}
        output_models = []
        for model in fp_result.report['models']:
            asset = assets_by_alias[model['import_basename']]
            ref = model['source_reference']
            key = (model['import_basename'], tuple(ref['offset']), tuple(ref['rotation']), tuple(ref['scale']))
            output_models.append(dict(asset, source_reference=asdict(original_by_alias[key]),
                                      transform=model['transform']))
        _check_records(symbol_result.cds, fp_result.fpl, target_name, mapping, output_models)
        symbol_result.report.update(physical_pin_mapping_verified=True,
            pin_mapping_verification_scope=mapping['scope'])
        for diagnostic in symbol_result.report['diagnostics']:
            if diagnostic['code']=='SYMBOL_FOOTPRINT_MAPPING_UNVERIFIED':
                diagnostic.update(code='SYMBOL_FOOTPRINT_LINK_VERIFIED', severity='info', message=mapping['scope'])
        symbol_result.report['counts']['assumptions'] = sum(
            d['severity']=='assumption' for d in symbol_result.report['diagnostics'])
        fp_result.report['models'] = output_models
        for diagnostic in fp_result.report['diagnostics']:
            if diagnostic['code']=='MODEL_FOLDER':
                diagnostic['message'] = 'Set FreePCB2 3d_folder to <bundle>/'+RUNTIME_FOLDER+'; project units MM'
        entry.update(status='generated_with_loss', source_target_mapping_verified=True,
                     target_footprint=target_name, symbol=folder+'/symbol.cds', footprint=folder+'/footprint.fpl',
                     models=output_models, chain_complete=not missing and bool(output_models),
                     symbol_conversion=symbol_result.report, footprint_conversion=fp_result.report)
        output_folder = stage/folder
        output_folder.mkdir(parents=True, exist_ok=True)
        (output_folder/'symbol.cds').write_bytes(symbol_result.cds.encode('cp1251'))
        (output_folder/'footprint.fpl').write_bytes(fp_result.fpl.encode('cp1251'))
    except LinkError as error:
        entry.update(status=error.status, error=dict(code=error.code, message=str(error), **error.details))
    except (LossySymbolConversionError, LossyConversionError) as error:
        entry.update(status='rejected_loss', error=dict(code='STRICT_REJECTED', message=str(error)), rejection_report=error.report)
    except FileNotFoundError as error:
        entry.update(status='unresolved', error=dict(code='SOURCE_MISSING', message=str(error)))
    except (ValueError, OSError) as error:
        entry.update(status='failed', error=dict(code='CONVERSION_FAILED', message=str(error)))
    except Exception as error:
        entry.update(status='failed', error=dict(code='UNEXPECTED_CONVERSION_ERROR', message=str(error),
                                                error_type=type(error).__name__))
    if entry['status'] not in SUCCESS:
        # A failed item cannot leave a current target artifact, even on an I/O
        # failure after writing its first file. Private staging files only.
        entry.update(source_target_mapping_verified=False, chain_complete=False)
        for key in ('symbol', 'footprint'):
            if key in entry:
                _portable_path(stage, entry.pop(key)).unlink(missing_ok=True)
        entry.pop('models', None)
        if 'symbol_conversion' in entry:
            report = entry['symbol_conversion']
            report['target_output_generated'] = False
            if 'artifact_sha256' in report:
                report['proposed_artifact_sha256'] = report.pop('artifact_sha256')
        assets.rollback(checkpoint)
    report_path = stage/entry['report']
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(json_bytes(entry))
    return {k: v for k, v in entry.items() if k not in ('symbol_conversion', 'footprint_conversion', 'rejection_report')}


def export_bundle(config_path: Path, output: Path, *, stl_root: Path = DEFAULT_STL_ROOT,
                  allow_missing_models: bool = False, strict: bool = False) -> dict:
    """Build a NEW output directory and publish it only after verification."""
    config_path, output, stl_root = Path(config_path), Path(output), Path(stl_root).resolve()
    config, raw = load_config(config_path)
    base = config_path.resolve().parent
    validate_output_path(output, config_path, stl_root)
    for directory in [base/config['footprint_libraries'][key] for key in config['footprint_libraries']] + [
            (base/c['symbol_library']).parent for c in config['components']]:
        if output.resolve().is_relative_to(directory.resolve()):
            raise ValueError('Bundle output cannot be inside a source library directory')
    if output.exists() or output.is_symlink():
        raise ValueError('Bundle output must be a new directory; existing output is never replaced')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.component-bundle-', dir=output.parent) as temporary:
        stage = Path(temporary)/'bundle'
        stage.mkdir()
        assets, cache = Assets(stage), {}
        entries = [_convert_item(c, config, base, stage, assets, stl_root, cache,
                                 allow_missing_models, strict)
                   for c in sorted(config['components'], key=lambda c:c['id'])]
        used = {m['source_relative'] for entry in entries for m in entry.get('models', [])}
        models = assets.retain(used)
        instructions = ('KiCad -> FreePCB2 / Schemator component bundle\n\n'
            'Each generated component has symbol.cds, footprint.fpl and report.json.\n'
            'Native imports, netlist, fonts and 3D alignment are NOT GUI-validated.\n'
            'Copy the WHOLE directory. Paths in manifest.json are relative to it.\n'
            'Import the FPL libraries in FreePCB2 2.428 and CDS libraries in Schemator 1.429.\n'
            'Use project units MM; set the FreePCB2 OpenSCAD folder to:\n  <bundle>/'+RUNTIME_FOLDER+'\n'
            'Do not select the category tree models/: FPL imports use unique flat aliases.\n'
            'The category tree preserves original paths; both copies have the same SHA256.\n'
            'Only selected existing STL bytes were copied; meshes were not converted or inspected.\n'
            'Verify after copying with: python3 -B -m src.component_converter --verify <bundle>\n')
        (stage/'README.txt').write_bytes(instructions.encode())
        files = [dict(path=p.relative_to(stage).as_posix(), bytes=p.stat().st_size,
                      sha256=file_digest(p)) for p in sorted(stage.rglob('*')) if p.is_file()]
        summary = dict(Counter(e['status'] for e in entries))
        summary.update(total=len(entries), generated_components=sum(e['status'] in SUCCESS for e in entries),
                       complete_chains=sum(e['chain_complete'] for e in entries), models=len(models))
        manifest = dict(schema_version=1, kind='component_bundle', config_sha256=digest(raw),
            settings=dict(allow_missing_models=allow_missing_models, strict=strict,
                          aperture_defaults=config.get('aperture_defaults', {})),
            native_setup=dict(freepcb_version='2.428', schemator_version='1.429',
                              project_units='MM', **{'3d_folder':RUNTIME_FOLDER}),
            components=entries, models=models, files=files, summary=summary,
            artifact_hashes_verified=True, native_import_verified=False, gui_validated=False,
            model_geometry_validated=False)
        if 'symbol_curve_tolerance' in config:
            manifest['settings']['symbol_curve_tolerance_mm'] = config['symbol_curve_tolerance']
        if 'symbol_fill_tolerance' in config:
            manifest['settings']['symbol_fill_tolerance_mm'] = config['symbol_fill_tolerance']
        if 'symbol_unit_gap' in config:
            manifest['settings']['symbol_unit_gap_mm'] = config['symbol_unit_gap']
        if 'symbol_no_connect_policy' in config:
            manifest['settings']['symbol_no_connect_policy'] = config['symbol_no_connect_policy']
        if 'symbol_hidden_pin_policy' in config:
            manifest['settings']['symbol_hidden_pin_policy'] = config['symbol_hidden_pin_policy']
        if 'symbol_common_pin_policy' in config:
            manifest['settings']['symbol_common_pin_policy'] = config['symbol_common_pin_policy']
        for key in ('symbol_pin_name_policy', 'symbol_alternate_pin_policy'):
            if key in config:
                manifest['settings'][key] = config[key]
        (stage/'manifest.json').write_bytes(json_bytes(manifest))
        manifest = verify_bundle(stage)
        if output.exists() or output.is_symlink():
            raise ValueError('Output appeared while staging; refusing replacement')
        stage.rename(output)
    return manifest


def verify_bundle(root: Path) -> dict:
    """Verify relative asset hashes and CDS/FPL/model relationships after moving."""
    root = Path(root)
    manifest = json.loads((root/'manifest.json').read_bytes(), object_pairs_hook=_unique_pairs,
                          parse_constant=_invalid_constant)
    if manifest.get('schema_version') != 1 or manifest.get('kind') != 'component_bundle':
        raise ValueError('Invalid bundle manifest')
    indexed = set()
    for record in manifest['files']:
        path = _portable_path(root, record['path'])
        folded = record['path'].casefold()
        if folded in indexed or record['path']=='manifest.json':
            raise ValueError('Duplicate/reserved bundle file index')
        indexed.add(folded)
        if not path.is_file() or path.stat().st_size != record['bytes'] or file_digest(path) != record['sha256']:
            raise ValueError('Bundle file checksum mismatch: '+record['path'])
    actual = {p.relative_to(root).as_posix().casefold() for p in root.rglob('*') if p.is_file() or p.is_symlink()}
    if actual != indexed | {'manifest.json'}:
        raise ValueError('Bundle has missing or unindexed files/symlinks')
    assets = {model['source_relative']: model for model in manifest['models']}
    if len(assets) != len(manifest['models']):
        raise ValueError('Duplicate bundle model identity')
    for model in assets.values():
        if model['frame_validated']:
            raise ValueError('STL snapshot cannot claim validated geometry/frame')
        if model['canonical_path'] != 'models/'+model['source_relative']:
            raise ValueError('Model category tree path mismatch')
        for key in ('canonical_path', 'runtime_path'):
            path = _portable_path(root, model[key])
            if path.relative_to(root).as_posix().casefold() not in indexed or (
                    path.stat().st_size != model['bytes'] or file_digest(path) != model['sha256']):
                raise ValueError('Canonical/runtime model checksum mismatch')
        if PurePosixPath(model['runtime_path']).name != model['import_basename'] or str(
                PurePosixPath(model['runtime_path']).parent) != RUNTIME_FOLDER:
            raise ValueError('Model runtime alias/folder mismatch')
    used, component_ids = set(), set()
    for entry in manifest['components']:
        if entry['status'] not in SUCCESS | {'unresolved', 'ambiguous', 'failed', 'rejected_loss'}:
            raise ValueError('Unknown bundle component status')
        if entry['id'].casefold() in component_ids:
            raise ValueError('Duplicate bundle component id')
        component_ids.add(entry['id'].casefold())
        report_path = _portable_path(root, entry['report'])
        if entry['report'].casefold() not in indexed:
            raise ValueError('Unindexed component report')
        report = json.loads(report_path.read_bytes())
        if any(report.get(k) != v for k,v in entry.items()):
            raise ValueError('Component report differs from manifest')
        if entry['status'] not in SUCCESS:
            if entry.get('symbol') or entry.get('footprint') or entry['source_target_mapping_verified'] or entry['chain_complete']:
                raise ValueError('Failed bundle entry claims generated outputs')
            continue
        selected_models = entry['models']
        for model in selected_models:
            asset = assets.get(model['source_relative'])
            if asset is None or any(model.get(k) != v for k,v in asset.items()):
                raise ValueError('Component model does not match bundle asset')
            used.add(model['source_relative'])
        for key in ('symbol', 'footprint'):
            if entry[key].casefold() not in indexed:
                raise ValueError('Unindexed target artifact')
        cds = _portable_path(root, entry['symbol']).read_bytes().decode('cp1251')
        fpl = _portable_path(root, entry['footprint']).read_bytes().decode('cp1251')
        _check_records(cds, fpl, entry['target_footprint'], entry['pin_mapping'], selected_models)
        if digest(cds.encode('cp1251')) != report['symbol_conversion']['artifact_sha256']:
            raise ValueError('Symbol report artifact checksum mismatch')
        symbol_report = report['symbol_conversion']
        component_record = parse_cds(cds).components[0]
        if (symbol_report['target_component'] != json.loads(json_bytes(asdict(component_record))) or
                not symbol_report['physical_pin_mapping_verified'] or
                symbol_report['gui_validated'] or symbol_report['target_import_verified'] or
                report['footprint_conversion']['target']['gui_validated'] or
                report['footprint_conversion']['footprint'] != entry['target_footprint'] or
                report['footprint_conversion']['models'] != selected_models):
            raise ValueError('Target report does not describe verified records/scope')
        if not entry['source_target_mapping_verified'] or entry['native_import_verified'] or entry['gui_validated']:
            raise ValueError('Invalid bundle verification scope flags')
        if entry['chain_complete'] != (bool(selected_models) and not entry['model_resolution_diagnostics']):
            raise ValueError('Invalid complete-chain claim')
    if used != set(assets):
        raise ValueError('Unreferenced bundle model assets')
    if (manifest['native_setup'] != dict(freepcb_version='2.428', schemator_version='1.429',
            project_units='MM', **{'3d_folder':RUNTIME_FOLDER}) or
            manifest['native_import_verified'] or manifest['gui_validated'] or manifest['model_geometry_validated']):
        raise ValueError('Invalid native setup/verification scope')
    entries = manifest['components']
    summary = dict(Counter(e['status'] for e in entries))
    summary.update(total=len(entries), generated_components=sum(e['status'] in SUCCESS for e in entries),
                   complete_chains=sum(e['chain_complete'] for e in entries), models=len(assets))
    if manifest['summary'] != summary:
        raise ValueError('Bundle summary differs from verified entries')
    return manifest
