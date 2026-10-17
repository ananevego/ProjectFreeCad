"""Audit a small STEP -> binary STL demonstration against its CAD sources.

Requires Gmsh only for reading the source STEP solids. The STL checks use the
standard library and do not alter the existing model store.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def read_binary_stl(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 84:
        raise ValueError(f'{path}: STL header is truncated')
    triangles = struct.unpack_from('<I', data, 80)[0]
    if not triangles or len(data) != 84 + triangles * 50:
        raise ValueError(f'{path}: invalid binary STL triangle count/size')
    lower, upper = [math.inf] * 3, [-math.inf] * 3
    edges: dict[tuple, list[int]] = {}
    degenerate = 0
    signed_volume = 0.0
    for number in range(triangles):
        record = struct.unpack_from('<12fH', data, 84 + 50 * number)
        vertices = [tuple(record[index:index + 3]) for index in (3, 6, 9)]
        if any(not math.isfinite(value) for vertex in vertices for value in vertex):
            raise ValueError(f'{path}: non-finite coordinate in triangle {number}')
        for vertex in vertices:
            for axis, value in enumerate(vertex):
                lower[axis] = min(lower[axis], value)
                upper[axis] = max(upper[axis], value)
        a, b, c = vertices
        ab = [b[i] - a[i] for i in range(3)]
        ac = [c[i] - a[i] for i in range(3)]
        cross = (ab[1] * ac[2] - ab[2] * ac[1],
                 ab[2] * ac[0] - ab[0] * ac[2],
                 ab[0] * ac[1] - ab[1] * ac[0])
        if math.sqrt(sum(value * value for value in cross)) < 1e-12:
            degenerate += 1
        signed_volume += sum(a[i] * cross[i] for i in range(3)) / 6
        for index in range(3):
            first, second = vertices[index], vertices[(index + 1) % 3]
            key = tuple(sorted((first, second)))
            direction = 1 if (first, second) == key else -1
            edges.setdefault(key, []).append(direction)
    return {
        'bytes': len(data), 'sha256': sha256(path), 'triangles': triangles,
        'bbox_mm': lower + upper, 'signed_volume_mm3': signed_volume,
        'degenerate_triangles': degenerate,
        'boundary_edges': sum(len(directions) == 1 for directions in edges.values()),
        'nonmanifold_edges': sum(len(directions) > 2 for directions in edges.values()),
        'inconsistent_edges': sum(len(directions) == 2 and sum(directions) != 0
                                  for directions in edges.values()),
    }


def audit(source: Path, generated: Path, *, reference: Path | None = None,
          bbox_tolerance_mm: float = .01, volume_tolerance_fraction: float = .01) -> dict:
    try:
        import gmsh
    except ModuleNotFoundError as error:
        raise ValueError('Gmsh Python package is required to read STEP geometry') from error
    if bbox_tolerance_mm < 0 or not 0 <= volume_tolerance_fraction < 1:
        raise ValueError('Tolerances must be nonnegative; volume tolerance must be below 1')
    sources = sorted(path for path in source.rglob('*') if path.is_file()
                     and path.suffix.lower() in ('.step', '.stp'))
    if not sources:
        raise ValueError('No STEP/STP sources found')
    records = []
    gmsh.initialize()
    try:
        gmsh.option.setNumber('General.Terminal', 0)
        for path in sources:
            relative = path.relative_to(source)
            target_relative = relative.with_suffix('.stl')
            target = generated / target_relative
            gmsh.clear()
            gmsh.merge(str(path))
            solids = gmsh.model.getEntities(3)
            if not solids:
                raise ValueError(f'{relative}: no STEP solid')
            cad_bbox = list(gmsh.model.getBoundingBox(-1, -1))
            cad_volume = sum(gmsh.model.occ.getMass(3, tag) for _, tag in solids)
            if cad_volume <= 0:
                raise ValueError(f'{relative}: nonpositive CAD volume')
            mesh = read_binary_stl(target)
            bbox_error = max(abs(a - b) for a, b in zip(cad_bbox, mesh['bbox_mm']))
            volume_error = abs(mesh['signed_volume_mm3'] - cad_volume) / cad_volume
            passed = (mesh['degenerate_triangles'] == mesh['boundary_edges'] ==
                      mesh['nonmanifold_edges'] == mesh['inconsistent_edges'] == 0
                      and bbox_error <= bbox_tolerance_mm
                      and volume_error <= volume_tolerance_fraction)
            record = {
                'source': relative.as_posix(), 'source_sha256': sha256(path),
                'generated': target_relative.as_posix(), 'mesh': mesh,
                'cad_bbox_mm': cad_bbox, 'cad_volume_mm3': cad_volume,
                'bbox_max_abs_error_mm': bbox_error,
                'volume_relative_error': volume_error, 'passed': passed,
            }
            if reference is not None and (reference / target_relative).is_file():
                old = read_binary_stl(reference / target_relative)
                record['existing_stl'] = {
                    'sha256': old['sha256'], 'triangles': old['triangles'],
                    'bbox_mm': old['bbox_mm'],
                    'bbox_max_abs_difference_mm': max(abs(a - b) for a, b in zip(
                        old['bbox_mm'], mesh['bbox_mm'])),
                }
            records.append(record)
    finally:
        gmsh.finalize()
    return {
        'kind': 'step_stl_demo_audit', 'schema_version': 1,
        'gmsh_version': gmsh.GMSH_API_VERSION,
        'bbox_tolerance_mm': bbox_tolerance_mm,
        'volume_tolerance_fraction': volume_tolerance_fraction,
        'summary': {'sources': len(records), 'passed': sum(item['passed'] for item in records),
                    'failed': sum(not item['passed'] for item in records)},
        'items': records,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('generated', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--bbox-tolerance-mm', type=float, default=.01)
    parser.add_argument('--volume-tolerance-fraction', type=float, default=.01)
    args = parser.parse_args(argv)
    try:
        result = audit(args.source, args.generated, reference=args.reference,
                       bbox_tolerance_mm=args.bbox_tolerance_mm,
                       volume_tolerance_fraction=args.volume_tolerance_fraction)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result['summary'], sort_keys=True))
        return 0 if result['summary']['failed'] == 0 else 2
    except (OSError, ValueError, KeyError) as error:
        print(f'STEP/STL audit failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
