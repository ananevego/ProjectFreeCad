import importlib.util
import sys
import unittest
from pathlib import Path


MODULE = Path(__file__).parents[1] / 'src' / 'kicad_to_freepcb_footprint.py'
SPEC = importlib.util.spec_from_file_location('converter', MODULE)
converter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = converter
SPEC.loader.exec_module(converter)


class FootprintConverterTests(unittest.TestCase):
    def test_converts_supported_smd_footprint(self):
        source = '''(footprint "Demo" (fp_line (start -1 0) (end 1 0) (stroke (width 0.12)) (layer "F.SilkS")) (pad "1" smd roundrect (at -0.5 0) (size 1 1.2)) (pad "2" smd rect (at 0.5 0 90) (size 1 1.2)))'''
        result, warnings = converter.convert(converter.parse_sexpr(source))
        self.assertEqual(warnings, [])
        self.assertIn('[footprints]', result)
        self.assertIn('name: "Demo"', result)
        self.assertIn('n_pins: 2', result)
        self.assertIn('units: NM', result)
        self.assertIn('value_text:', result)
        self.assertIn('pin: "1" 0 0 0 0 ""', result)
        self.assertIn('top_pad: 3 1000000 600000 600000 0', result)
        self.assertIn('pin: "2" 0 1000000 0 90 ""', result)


if __name__ == '__main__':
    unittest.main()
