"""Internal footprint records: millimetres and the KiCad coordinate frame."""
from __future__ import annotations

from pathlib import Path
from pathlib import PurePosixPath
from dataclasses import dataclass
from dataclasses import field


ZERO = (0.0, 0.0, 0.0)


ONE = (1.0, 1.0, 1.0)


@dataclass(frozen=True)
class ConversionResult:
    fpl: str
    warnings: list[str]
    report: dict


@dataclass(frozen=True)
class ApertureSettings:
    """Margins per side, in mm; ratio is dimensionless. None means inherited."""
    mask_margin: float | None = None
    paste_margin: float | None = None
    paste_ratio: float | None = None


@dataclass(frozen=True)
class Pad:
    name: str
    kind: str
    shape: str
    x: float
    y: float
    rotation: float
    width: float
    height: float
    drill: float
    layers: tuple[str, ...]
    radius: float = 0.0
    apertures: ApertureSettings = field(default_factory=ApertureSettings)


@dataclass(frozen=True)
class FootprintText:
    kind: str
    content: str
    x: float
    y: float
    rotation: float
    size_x: float
    size_y: float
    thickness: float
    layer: str
    hidden: bool = False
    mirror: bool = False
    keep_upright: bool = True
    property_name: str | None = None


@dataclass(frozen=True)
class Polyline:
    points: tuple[tuple[float, float], ...]
    width: float
    layer: str
    closed: bool = False
    role: str = 'outline'


@dataclass(frozen=True)
class FilledPolygon:
    points: tuple[tuple[float, float], ...]
    width: float
    layer: str


@dataclass(frozen=True)
class FilledCircle:
    """Keep the source circle intact until fill/curve tolerances are known."""
    center: tuple[float, float]
    end: tuple[float, float]
    width: float
    layer: str


@dataclass(frozen=True)
class ModelReference:
    path: str
    offset: tuple[float, float, float] = ZERO
    rotation: tuple[float, float, float] = ZERO
    scale: tuple[float, float, float] = ONE


@dataclass
class Footprint:
    name: str
    pads: list[Pad]
    texts: list[FootprintText]
    polylines: list[Polyline]
    models: list[ModelReference]
    description: str = ''
    warnings: list[str] = field(default_factory=list)
    apertures: ApertureSettings = field(default_factory=ApertureSettings)
    filled_polygons: list[FilledPolygon] = field(default_factory=list)
    filled_circles: list[FilledCircle] = field(default_factory=list)


@dataclass(frozen=True)
class ModelMatch:
    reference: ModelReference
    stl_path: Path
    relative_path: PurePosixPath


@dataclass(frozen=True)
class ModelTransform:
    """Full STL -> target OpenSCAD transform: mm, degrees, unitless scale.

    Overrides the KiCad model transform. Default identity assumes the existing
    STL retains KiCad's 3D frame and millimetres; GUI/geometry not validated.
    """
    translation: tuple[float, float, float] = ZERO
    rotation: tuple[float, float, float] = ZERO
    scale: tuple[float, float, float] = ONE
