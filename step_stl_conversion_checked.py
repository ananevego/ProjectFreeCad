"""Convert KiCad STEP/STP 3D models to STL while preserving folder structure.

Expected project layout:
  step_stl_conversion_checked.py
  step_files/<KiCad folder>.3dshapes/*.step
  stl_files/<KiCad folder>.3dshapes/*.stl
"""

from __future__ import annotations

import argparse
from pathlib import Path

try:
    import gmsh
except ModuleNotFoundError as exc:
    raise SystemExit(
        "Module 'gmsh' is not installed. Install it with: python -m pip install gmsh"
    ) from exc


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT_DIR / "step_files"
DEFAULT_OUTPUT = ROOT_DIR / "stl_files"


def configure_mesh(mesh_size_min: float, mesh_size_max: float) -> None:
    """Apply Gmsh mesh options used for STEP -> STL conversion."""
    gmsh.option.setNumber("General.Terminal", 1)
    gmsh.option.setNumber("Mesh.Algorithm", 6)
    gmsh.option.setNumber("Mesh.MeshSizeMin", mesh_size_min)
    gmsh.option.setNumber("Mesh.MeshSizeMax", mesh_size_max)
    gmsh.option.setNumber("Mesh.MeshSizeFromPoints", 0)
    gmsh.option.setNumber("Mesh.CharacteristicLengthMax", mesh_size_max)
    gmsh.option.setNumber("Mesh.CharacteristicLengthFactor", 2)
    gmsh.option.setNumber("Mesh.Binary", 1)
    gmsh.option.setNumber("Mesh.RecombinationAlgorithm", 0)
    gmsh.option.setNumber("Mesh.RecombineAll", 1)
    gmsh.option.setNumber("Mesh.Smoothing", 1)


def iter_step_files(input_dir: Path):
    for path in sorted(input_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".step", ".stp"}:
            yield path


def convert_file(input_file: Path, output_file: Path, mesh_size_min: float, mesh_size_max: float) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    gmsh.clear()
    configure_mesh(mesh_size_min, mesh_size_max)
    gmsh.merge(str(input_file))
    gmsh.model.mesh.generate(2)
    gmsh.write(str(output_file))


def convert_tree(input_dir: Path, output_dir: Path, mesh_size_min: float, mesh_size_max: float) -> int:
    if not input_dir.exists():
        raise SystemExit(f"Input directory does not exist: {input_dir}")

    files = list(iter_step_files(input_dir))
    print(f"Found STEP/STP files: {len(files)}")

    converted = 0
    failed = 0

    gmsh.initialize()
    try:
        for input_file in files:
            relative = input_file.relative_to(input_dir)
            output_file = output_dir / relative.with_suffix(".stl")
            try:
                print(f"Converting: {relative}")
                convert_file(input_file, output_file, mesh_size_min, mesh_size_max)
                converted += 1
                print(f"  OK -> {output_file.relative_to(output_dir)}")
            except Exception as exc:
                failed += 1
                print(f"  ERROR -> {relative}: {exc}")
    finally:
        gmsh.finalize()

    print(f"Finished. Converted: {converted}. Failed: {failed}.")
    return 0 if failed == 0 else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert KiCad STEP/STP models to STL with Gmsh.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Input step_files directory.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Output stl_files directory.")
    parser.add_argument("--mesh-min", type=float, default=0.01, help="Minimum mesh size. Lower means more detail.")
    parser.add_argument("--mesh-max", type=float, default=0.5, help="Maximum mesh size. Lower means more detail.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return convert_tree(args.input, args.output, args.mesh_min, args.mesh_max)


if __name__ == "__main__":
    raise SystemExit(main())
