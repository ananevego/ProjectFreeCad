"""Checks independent of the optional Gmsh installation."""

from pathlib import Path
import struct
import tempfile
import unittest

from src.step_stl_audit import read_binary_stl


class BinaryStlAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'tetra.stl'
        a, b, c, d = (0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (0., 0., 1.)
        self.faces = [(a, c, b), (a, b, d), (a, d, c), (b, c, d)]

    def write_faces(self, faces):
        data = bytearray(80) + bytearray(struct.pack('<I', len(faces)))
        for face in faces:
            data.extend(struct.pack('<12fH', 0, 0, 0, *face[0], *face[1], *face[2], 0))
        self.path.write_bytes(data)

    def test_closed_oriented_tetrahedron(self):
        self.write_faces(self.faces)
        result = read_binary_stl(self.path)
        self.assertEqual(result['triangles'], 4)
        self.assertEqual(result['bbox_mm'], [0, 0, 0, 1, 1, 1])
        self.assertAlmostEqual(result['signed_volume_mm3'], 1 / 6)
        self.assertEqual([result[key] for key in ('degenerate_triangles', 'boundary_edges',
                                                  'nonmanifold_edges', 'inconsistent_edges')], [0] * 4)

    def test_reversed_face_and_truncation_are_detected(self):
        a, b, c = self.faces[0]
        self.write_faces([(a, c, b), *self.faces[1:]])
        self.assertGreater(read_binary_stl(self.path)['inconsistent_edges'], 0)
        self.path.write_bytes(self.path.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, 'triangle count/size'):
            read_binary_stl(self.path)


if __name__ == '__main__':
    unittest.main()
