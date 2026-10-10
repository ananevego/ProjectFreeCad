"""Resolve existing STL references using paths and metadata, never mesh contents."""
from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
import math

from .errors import ConversionError
from .model import ModelMatch, ModelReference, ModelTransform, ONE, ZERO


DEFAULT_STL_ROOT = Path(__file__).resolve().parents[2] / 'stl_files'


def match_models(references: list[ModelReference], stl_root: Path,
                 warnings: list[str]) -> list[ModelMatch]:
    matches = []
    base = stl_root.resolve()
    if not references:
        warnings.append('MODEL_MISSING: no KiCad model reference; no basename guessing')
    for reference in references:
        parts = PurePosixPath(reference.path.replace('\\', '/')).parts
        indices = [i for i, part in enumerate(parts) if part.endswith('.3dshapes')]
        if len(indices) != 1 or PurePosixPath(reference.path).suffix.lower() not in {'.step', '.stp', '.wrl', '.stl'}:
            warnings.append(f'MODEL_UNRESOLVED: expected a .3dshapes path in {reference.path}')
            continue
        relative = PurePosixPath(*parts[indices[0]:]).with_suffix('.stl')
        if '..' in relative.parts or len(relative.parts) != 2:
            warnings.append(f'MODEL_UNRESOLVED: unsupported relative model path {relative}')
            continue
        candidate = base.joinpath(*relative.parts).resolve()
        if not candidate.is_relative_to(base):
            raise ConversionError(f'Model path escapes STL root: {relative}')
        if not candidate.is_file():
            warnings.append(f'MODEL_MISSING: {relative}')
            continue
        if candidate.stat().st_size == 0:
            raise ConversionError(f'Empty existing STL: {relative}')
        match = ModelMatch(reference, candidate, relative)
        if match not in matches:
            matches.append(match)
    if len({m.stl_path.parent for m in matches}) > 1:
        raise ConversionError('FreePCB2 2.428 basename imports require one 3d_folder; models span multiple folders')
    return matches


def resolve_model_transform(reference: ModelReference, override: ModelTransform | None,
                            warnings: list[str]) -> ModelTransform:
    if override is None:
        if (reference.offset, reference.rotation, reference.scale) != (ZERO, ZERO, ONE):
            raise ConversionError('Non-identity KiCad 3D transform requires an explicit target ModelTransform')
        warnings.append('MODEL_FRAME_UNVERIFIED: identity assumes STL coordinates/units match KiCad 3D (mm)')
        return ModelTransform()
    vectors = (override.translation, override.rotation, override.scale)
    if any(len(v) != 3 for v in vectors) or not all(math.isfinite(n) for v in vectors for n in v) or 0 in override.scale:
        raise ConversionError('Invalid target model transform')
    warnings.append('MODEL_TRANSFORM_OVERRIDE: explicit full target transform replaces KiCad transform; GUI validation pending')
    return override


def openscad_code(match: ModelMatch, transform: ModelTransform) -> list[str]:
    filename = match.stl_path.name
    if any(c in filename for c in '`"\n\r'):
        raise ConversionError('Model basename cannot be represented in OpenSCAD import')
    def vector(values):
        return '[' + ','.join(f'{v:.9g}' for v in values) + ']'
    return [
        'translate([0,0,0]) // (automatic adjustment when moving the footprint origin)',
        'scale([1,1,1]) // (automatic adjustment when changing the project units)',
        '{', f'  translate({vector(transform.translation)})',
        f'  rotate({vector(transform.rotation)})', f'  scale({vector(transform.scale)})',
        f'  import(`{filename}`);', '}',
    ]
