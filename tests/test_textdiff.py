"""Tests del diff de texto (textdiff.py)."""
import unittest

import _path  # noqa: F401
from harness_candy.codeedit import apply_unified_diff
from harness_candy.textdiff import DiffStats, diff_lineas, diff_stats, resaltar_cambios, resumen_diff, similarity, unified_diff

A = "linea uno\nlinea dos\nlinea tres\n"
B = "linea uno\nlinea DOS\nlinea cuatro\n"


class TestTextDiff(unittest.TestCase):
    def test_diff_lineas(self):
        ops = diff_lineas(A, B)
        tags = [t for t, _ in ops]
        self.assertIn("-", tags)
        self.assertIn("+", tags)
        self.assertIn("=", tags)

    def test_similarity(self):
        self.assertEqual(similarity(A, A), 1.0)
        self.assertLess(similarity(A, B), 1.0)
        self.assertGreater(similarity(A, B), 0.3)
        self.assertEqual(similarity("", ""), 1.0)

    def test_unified_diff_compatible_con_codeedit(self):
        py_a = "def f():\n    return 1\n\n\ndef g():\n    return 2\n"
        py_b = "def f():\n    return 10\n\n\ndef g():\n    return 2\n"
        diff = unified_diff(py_a, py_b, fromfile="x.py", tofile="x.py", n=1)
        self.assertIn("--- a/x.py", diff)
        self.assertIn("+++ b/x.py", diff)
        self.assertIn("@@", diff)
        out = apply_unified_diff(py_a, diff)
        self.assertIn("return 10", out)
        self.assertIn("return 2", out)

    def test_diff_stats(self):
        st = diff_stats(A, B)
        self.assertIsInstance(st, DiffStats)
        self.assertEqual(st.anadidas, 2)
        self.assertEqual(st.eliminadas, 2)
        self.assertEqual(st.iguales, 1)
        self.assertGreater(st.bloques, 0)
        self.assertGreater(st.ratio, 0)
        d = st.to_dict()
        self.assertEqual(d["anadidas"], 2)

    def test_resaltar_cambios(self):
        a, b = resaltar_cambios("return 1", "return 2")
        self.assertIn("[1]", a)
        self.assertIn("‹2›", b)

    def test_resumen_diff(self):
        r = resumen_diff(A, B)
        self.assertIn("diff:", r)
        self.assertIn("similitud", r)
        r2 = resumen_diff(A, A)
        self.assertIn("+0 -0", r2)

    def test_unified_diff_igual(self):
        diff = unified_diff(A, A)
        self.assertNotIn("@@", diff)


if __name__ == "__main__":
    unittest.main()
