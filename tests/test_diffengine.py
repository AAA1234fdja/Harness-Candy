"""Tests del diff semantico AST (diffengine.py)."""
import unittest

import _path  # noqa: F401
from harness_candy.diffengine import CodeDiff, ast_diff

A = "import os\n\ndef a(x):\n    return x + 1\n\nclass C:\n    def m(self):\n        return 1\n"
B = "import sys\n\ndef a(x):\n    return x + 2\n\ndef b():\n    return 0\n\nclass C:\n    def m(self):\n        return 1\n\nclass D:\n    pass\n"


class TestDiffEngine(unittest.TestCase):
    def test_cambios_basicos(self):
        d = ast_diff(A, B)
        self.assertEqual(d.funciones_anadidas, ["b"])
        self.assertEqual(d.funciones_eliminadas, [])
        self.assertEqual(len(d.funciones_modificadas), 1)
        mod = d.funciones_modificadas[0]
        self.assertEqual(mod["name"], "a")
        self.assertTrue(mod["cambio_body"])
        self.assertFalse(mod["cambio_firma"])
        self.assertEqual(d.imports_anadidos, ["sys"])
        self.assertEqual(d.imports_eliminados, ["os"])
        self.assertEqual(d.clases_anadidas, ["D"])
        self.assertEqual(d.clases_eliminadas, [])
        self.assertTrue(d.hay_cambios)
        self.assertGreater(d.n_cambios, 0)

    def test_sin_cambios(self):
        d = ast_diff(A, A)
        self.assertFalse(d.hay_cambios)
        self.assertEqual(d.n_cambios, 0)

    def test_cambio_de_firma(self):
        d = ast_diff("def f(x):\n    return x\n", "def f(x, y=1):\n    return x\n")
        self.assertTrue(d.funciones_modificadas[0]["cambio_firma"])

    def test_funcion_eliminada(self):
        d = ast_diff("def f():\n    return 1\ndef g():\n    return 2\n", "def f():\n    return 1\n")
        self.assertEqual(d.funciones_eliminadas, ["g"])

    def test_to_dict(self):
        d = ast_diff(A, B).to_dict()
        for k in ("funciones_anadidas", "funciones_eliminadas", "funciones_modificadas", "imports_anadidos", "imports_eliminados", "clases_anadidas", "clases_eliminadas"):
            self.assertIn(k, d)
        self.assertIsInstance(d, dict)

    def test_codediff_vacio(self):
        d = CodeDiff()
        self.assertFalse(d.hay_cambios)


if __name__ == "__main__":
    unittest.main()
