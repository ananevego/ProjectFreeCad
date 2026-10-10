"""Protected output paths and atomic replacement of individual output files."""
from __future__ import annotations

from pathlib import Path
import os
import tempfile

from .errors import ConversionError
from .model_matching import DEFAULT_STL_ROOT


def validate_output_path(path: Path, source: Path, stl_root: Path) -> None:
    resolved = path.resolve()
    if resolved == source.resolve():
        raise ConversionError('Output must differ from input')
    for protected in (DEFAULT_STL_ROOT, DEFAULT_STL_ROOT.parent / 'step_files', stl_root):
        if resolved.is_relative_to(protected.resolve()):
            raise ConversionError('Output cannot be inside model storage')


def atomic_write(path: Path, data: bytes) -> None:
    """Replace an output only after all bytes are written successfully."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.freepcb-', delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()
