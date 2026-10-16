"""Create a new native validation kit or verify one without source/model stores."""
import argparse
from pathlib import Path
import sys

from .kit import build_kit
from .portable import verify_kit
from src.footprint_converter.model_matching import DEFAULT_STL_ROOT


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', nargs='?', type=Path)
    p.add_argument('--project', type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument('--stl-root', type=Path, default=DEFAULT_STL_ROOT)
    p.add_argument('--allow-missing-models', action='store_true')
    p.add_argument('--verify', type=Path)
    args = p.parse_args(argv)
    if bool(args.output) == bool(args.verify): p.error('Use OUTPUT or --verify KIT')
    try:
        m = verify_kit(args.verify) if args.verify else build_kit(args.project, args.output,
            stl_root=args.stl_root, allow_missing_models=args.allow_missing_models)
        s = m['summary']
        print(f"Native kit: {s['generated_components']} components, {s['footprints']} 2D controls, {s['models']} model aliases; native checks remain not_run.")
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Native kit failed: '+str(error), file=sys.stderr); return 1


if __name__ == '__main__': raise SystemExit(main())
