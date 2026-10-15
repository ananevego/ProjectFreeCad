"""Conversion failures, including strict rejection with its report."""
from __future__ import annotations




class ConversionError(ValueError):
    """Input cannot safely be represented by the supported target subset."""


class PadGeometryError(ConversionError):
    """A source pad has no representation in the confirmed native profile."""
    def __init__(self, code: str, message: str, source: list, **details):
        from copy import deepcopy
        self.report = dict(schema_version=1, status='failed', diagnostics=[
            dict(code=code, severity='error', message=message)],
            pad_geometry=dict(source_pad=deepcopy(source), **details,
                native_gui_validated=False, manufacturing_validated=False))
        super().__init__(message)


class LossyConversionError(ConversionError):
    def __init__(self, report: dict):
        self.report = report
        codes = sorted({d['code'] for d in report['diagnostics'] if d['severity'] == 'loss'})
        super().__init__('Strict conversion rejected data loss: ' + ', '.join(codes))
