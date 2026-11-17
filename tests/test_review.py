"""Tests del ReviewAgent (WEV sobre diffs de PR)."""
import unittest

import _path  # noqa: F401
from harness_candy.review import ReviewAgent

DIFF_OK = """diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,4 @@
 def main():
     pass
+def nuevo():
+    return 42
diff --git a/docs/x.md b/docs/x.md
--- a/docs/x.md
+++ b/docs/x.md
@@ -1 +1 @@
-hola
+adios
"""

DIFF_FUERA_DE_ALCANCE = """diff --git a/otra/ruta.txt b/otra/ruta.txt
--- a/otra/ruta.txt
+++ b/otra/ruta.txt
@@ -1 +1 @@
-a
+b
"""

DIFF_CON_SECRETO = """diff --git a/src/c.py b/src/c.py
--- a/src/c.py
+++ b/src/c.py
@@ -1 +1,2 @@
 x = 1
+clave = "sk-abcdefghijklmnopqrstuvwxyz1234"
"""

DIFF_CON_ERROR_SINTAXIS = """diff --git a/src/malo.py b/src/malo.py
--- a/src/malo.py
+++ b/src/malo.py
@@ -1 +1,2 @@
 def roto(:
+    pass
"""


class TestReviewAgent(unittest.TestCase):
    def setUp(self):
        self.rev = ReviewAgent()

    def test_diff_limpio_aprobado(self):
        msg = self.rev.review_diff(DIFF_OK)
        self.assertEqual(msg.veredicto, "aprobado")
        self.assertTrue(msg.checks["diff_en_alcance"])
        self.assertTrue(msg.checks["sintaxis_ok"])
        self.assertTrue(msg.checks["sin_secretos_en_diff"])
        self.assertEqual(msg.hallazgos, [])
        self.assertEqual(msg.envelope.protocol, "wev")

    def test_fuera_de_alcance_rechazado(self):
        msg = self.rev.review_diff(DIFF_FUERA_DE_ALCANCE)
        self.assertEqual(msg.veredicto, "rechazado")
        self.assertFalse(msg.checks["diff_en_alcance"])
        self.assertTrue(any(h.herramienta == "diff_fuera_de_alcance" or "alcance" in h.detalle for h in msg.hallazgos))

    def test_secreto_en_diff_bloqueado(self):
        msg = self.rev.review_diff(DIFF_CON_SECRETO)
        self.assertEqual(msg.veredicto, "rechazado")
        self.assertFalse(msg.checks["sin_secretos_en_diff"])
        self.assertTrue(any(h.severidad == "critica" for h in msg.hallazgos))

    def test_error_de_sintaxis_rechazado(self):
        msg = self.rev.review_diff(DIFF_CON_ERROR_SINTAXIS)
        self.assertEqual(msg.veredicto, "rechazado")
        self.assertFalse(msg.checks["sintaxis_ok"])
        self.assertTrue(any(h.herramienta == "review_sintaxis" for h in msg.hallazgos))

    def test_prefixes_personalizados(self):
        rev = ReviewAgent(allowed_prefixes=("otra/",))
        msg = rev.review_diff(DIFF_FUERA_DE_ALCANCE)
        self.assertEqual(msg.veredicto, "aprobado")

    def test_mensaje_es_protocolo_valido(self):
        from harness_candy.protocols import validate

        msg = self.rev.review_diff(DIFF_OK)
        validate(msg.to_dict())  # no lanza: cumple el esquema wev


if __name__ == "__main__":
    unittest.main()
