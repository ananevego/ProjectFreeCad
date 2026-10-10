"""Compatible Python/CLI entry point for the modular FreePCB2 converter.

Target: FreePCB2 2.428, revision 3af0f9b9a234c97f2d21455c936abeb8439d2d45.
Implementation lives in src.footprint_converter; model files are never rewritten.
"""
import os  # Shared module retained for callers patching the legacy atomic writer.
import sys
from pathlib import Path

# Absolute-path execution and importlib loading must work outside the repository.
_PROJECT_ROOT = str(Path(__file__).resolve().parents[1])
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.footprint_converter import *  # noqa: F403 -- intentional legacy API
from src.footprint_converter import __all__

if __name__ == '__main__':
    raise SystemExit(main())
