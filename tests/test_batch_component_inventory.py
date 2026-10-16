"""Bulk candidates require exact identifiers and literal unique native numbers."""
import json
from pathlib import Path
import tempfile
import unittest

from src.component_converter.batch_inventory import inventory_links
from src.symbol_converter.batch import run_batch as symbol_batch, json_bytes
from src.symbol_converter.audit import audit_batch as symbol_audit
from src.footprint_converter.batch import run_batch as footprint_batch
from src.footprint_converter.audit import audit_batch as footprint_audit
from src.footprint_converter.model import ApertureSettings
from test_symbol_batch import basic
from test_symbol_converter import library
from test_footprint_converter import source_pad


class BatchComponentInventoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.symbols, self.footprints = (self.root / n for n in ('symbols', 'footprints'))
        self.symbols.mkdir()
        category = self.footprints / 'Demo.pretty'
        category.mkdir(parents=True)
        for name, body in [('One', source_pad(name='1')), ('Two', source_pad(name='2')),
                           ('Repeated', source_pad(name='1') + source_pad(name='1', at='2 0')),
                           ('Slot', source_pad(kind='thru_hole', extra='(drill oval .8 .5)'))]:
            (category / (name + '.kicad_mod')).write_text('(footprint "' + name + '" ' + body + ')')
        definitions = []
        for name, identifier in [('Good', 'Demo:One'), ('Mismatch', 'Demo:Two'), ('Ambiguous', 'Demo:Repeated'),
                                 ('RefusedFP', 'Demo:Slot'), ('NoDefault', ''), ('Absent', 'Demo:Missing'), ('Wildcard', 'Demo:*')]:
            definitions.append(basic(name).replace('(property "Footprint" ""', '(property "Footprint" "' + identifier + '"'))
        definitions.append(basic('Hidden', '(hide yes)'))
        (self.symbols / 'Demo.kicad_sym').write_text(library(*definitions))
        self.sb, self.fb = self.root / 'sb', self.root / 'fb'
        symbol_batch(self.symbols, self.sb)
        footprint_batch(self.footprints, self.fb, stl_root=self.root / 'models', aperture_defaults=ApertureSettings(.05, 0, 0))
        self.sa, self.fa = self.root / 'sa.json', self.root / 'fa.json'
        self.sa.write_bytes(json_bytes(symbol_audit(self.symbols, self.sb)))
        self.fa.write_bytes(json_bytes(footprint_audit(self.footprints, self.fb)))

    def inventory(self):
        return inventory_links(self.sb, self.sa, self.fb, self.fa)

    def test_only_literal_unique_matching_pin_sets_are_candidates(self):
        result = self.inventory()
        items = {item['symbol']: item for item in result['items']}
        self.assertEqual(items['Good']['status'], 'eligible_for_linked_export')
        self.assertEqual(items['Good']['physical_numbers'], ['1'])
        expected = dict(Mismatch='pin_pad_numbers_differ', Ambiguous='footprint_numbers_ambiguous',
                        RefusedFP='footprint_refused', NoDefault='footprint_unspecified', Absent='footprint_absent',
                        Wildcard='footprint_identifier_not_literal', Hidden='symbol_refused')
        for name, status in expected.items():
            self.assertEqual(items[name]['status'], status)
        self.assertEqual(sum(result['summary']['statuses'].values()), 8)

    def test_candidate_inventory_does_not_assign_footprints_or_claim_native_checks(self):
        result = self.inventory()
        self.assertFalse(result['cds_footprints_assigned'])
        self.assertFalse(result['native_netlist_verified'])
        self.assertTrue(all(not i['cds_footprint_assigned'] for i in result['items']))
        manifest = json.loads((self.sb / 'manifest.json').read_bytes())
        good = next(e for e in manifest['entries'] if e['symbol'] == 'Good')
        self.assertIn('"PART"', (self.sb / good['output_file']).read_text(encoding='cp1251'))

    def test_changed_candidate_native_artifact_fails_instead_of_becoming_a_match(self):
        manifest = json.loads((self.fb / 'manifest.json').read_bytes())
        one = next(e for e in manifest['entries'] if e['source'].endswith('/One.kicad_mod'))
        path = self.fb / one['output_file']
        path.write_bytes(path.read_bytes() + b'\n')
        with self.assertRaisesRegex(ValueError, 'checksum'):
            self.inventory()

    def test_mismatched_audit_is_rejected(self):
        audit = json.loads(self.sa.read_bytes())
        audit['batch_manifest_sha256'] = '0' * 64
        self.sa.write_bytes(json_bytes(audit))
        with self.assertRaisesRegex(ValueError, 'matching completed'):
            self.inventory()


if __name__ == '__main__':
    unittest.main()
