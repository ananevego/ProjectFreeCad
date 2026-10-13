"""Build a new portable component bundle, or verify it after relocation."""
import argparse
from pathlib import Path
import sys

from .bundle import export_bundle, verify_bundle
from src.footprint_converter.model_matching import DEFAULT_STL_ROOT


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path, nargs='?')
    parser.add_argument('output', type=Path, nargs='?')
    parser.add_argument('--stl-root', type=Path, default=DEFAULT_STL_ROOT)
    parser.add_argument('--allow-missing-models', action='store_true')
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--verify', type=Path, help='Verify an existing bundle without writing')
    args = parser.parse_args(argv)
    if args.verify is not None and (args.config or args.output) or args.verify is None and not (args.config and args.output):
        parser.error('Use CONFIG OUTPUT, or --verify BUNDLE')
    try:
        manifest = verify_bundle(args.verify) if args.verify else export_bundle(args.config, args.output,
            stl_root=args.stl_root, allow_missing_models=args.allow_missing_models, strict=args.strict)
        summary = manifest['summary']
        print(f"{summary['generated_components']}/{summary['total']} components, "
              f"{summary['complete_chains']} complete chains, {summary['models']} existing model assets; "
              'native GUI/import and 3D geometry unverified.')
        return 0 if summary['generated_components'] == summary['total'] else 2
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f'Component bundle failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
