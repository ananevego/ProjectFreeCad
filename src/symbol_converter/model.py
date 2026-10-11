"""Source symbol data, in millimetres and KiCad library coordinates (Y up).

No target record mapping is implied by this model. Raw records are retained
so text effects, metadata and unsupported extensions remain inspectable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from copy import deepcopy


class SymbolParseError(ValueError):
    """An invalid or ambiguous source library cannot be normalized."""


@dataclass
class Diagnostic:
    code: str
    message: str
    severity: str = 'warning'
    unit: int | None = None
    style: int | None = None
    pin_number: str | None = None


@dataclass
class Property:
    name: str
    value: str
    at: tuple[float, float, float]
    hidden: bool
    raw: list


@dataclass
class Pin:
    number: str
    name: str
    at: tuple[float, float, float]
    length: float
    electrical_type: str
    graphic_style: str
    hidden: bool
    name_size: tuple[float, float]
    number_size: tuple[float, float]
    alternates: list[dict] = field(default_factory=list)
    raw: list = field(default_factory=list)


@dataclass
class Graphic:
    kind: str
    geometry: dict
    width: float
    fill: str
    raw: list


@dataclass
class Unit:
    number: int
    style: int
    source_id: str
    display_name: str | None = None
    pins: list[Pin] = field(default_factory=list)
    graphics: list[Graphic] = field(default_factory=list)


@dataclass
class Symbol:
    name: str
    properties: dict[str, Property] = field(default_factory=dict)
    units: list[Unit] = field(default_factory=list)
    extends: str | None = None
    inheritance_chain: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    alias_of: str | None = None
    unit_count: int = 1
    pin_names_hidden: bool = False
    pin_numbers_hidden: bool = False
    pin_name_offset: float = 0.508
    in_bom: bool = True
    on_board: bool = True
    power: bool = False
    diagnostics: list[Diagnostic] = field(default_factory=list)
    raw: list = field(default_factory=list)

    def pins_for(self, unit: int = 1, style: int = 1) -> list[Pin]:
        """Include common records; never deduplicate or infer physical pads."""
        if not 1 <= unit <= self.unit_count or style not in (1, 2):
            raise SymbolParseError('Invalid unit/body style selection')
        return [pin for block in self.units
                if block.number in (0, unit) and block.style in (0, style)
                for pin in block.pins]

    @property
    def source_ready(self) -> bool:
        return not self.diagnostics


@dataclass
class Library:
    source_format: str
    version: str
    symbols: dict[str, Symbol]
    aliases: dict[str, str] = field(default_factory=dict)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    raw_metadata: list = field(default_factory=list)

    def get_symbol(self, name: str) -> Symbol:
        try:
            canonical = self.aliases.get(name)
            if canonical is None:
                return self.symbols[name]
            # KiCad's legacy reader materializes an alias with the parent's
            # field attributes and the alias name as its effective Value.
            symbol = deepcopy(self.symbols[canonical])
            symbol.name = name
            symbol.alias_of = canonical
            symbol.aliases = []
            symbol.inheritance_chain = [canonical]
            symbol.properties['Value'].value = name
            return symbol
        except KeyError as error:
            raise SymbolParseError(f'Unknown symbol: {name}') from error
