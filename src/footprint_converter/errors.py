"""Conversion failures, including strict rejection with its report."""
from __future__ import annotations




class ConversionError(ValueError):
    """Input cannot safely be represented by the supported target subset."""


class LossyConversionError(ConversionError):
    def __init__(self, report: dict):
        self.report = report
        codes = sorted({d['code'] for d in report['diagnostics'] if d['severity'] == 'loss'})
        super().__init__('Strict conversion rejected data loss: ' + ', '.join(codes))
