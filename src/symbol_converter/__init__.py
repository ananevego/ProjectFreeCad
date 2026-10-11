"""KiCad source symbol inspection; target Schemator writer is not implemented."""
from .model import Library, Symbol, SymbolParseError
from .modern import parse_modern
from .legacy import parse_legacy


def parse_library(text: str) -> Library:
    text = text.lstrip('\ufeff')
    if text.lstrip().startswith('('):
        return parse_modern(text)
    return parse_legacy(text)


__all__ = ['Library', 'Symbol', 'SymbolParseError', 'parse_library']
