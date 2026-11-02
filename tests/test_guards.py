"""Tests de los guardrails de salida componibles."""
import unittest

import _path  # noqa: F401
from harness_candy.guards import (
    ForbiddenPatternsGuard,
    GuardPipeline,
    JsonSchemaGuard,
    MaxLengthGuard,
    NoSecretsGuard,
    RequiredKeysGuard,
    default_pipeline,
)
from harness_candy.schemas import SCHEMAS


class TestNoSecretsGuard(unittest.TestCase):
    def test_bloquea_pii_y_secretos(self):
        g = NoSecretsGuard()
        texto = "Contacto: juan@example.com, tarjeta 4111 1111 1111 1111, clave sk-abcdefghijklmnopqrstuvwxyz1234"
        hallazgos = g.check(texto)
        self.assertTrue(hallazgos)
        self.assertTrue(all(h.severidad == "critica" for h in hallazgos))
        self.assertTrue(all(h.herramienta == "no_secretos" for h in hallazgos))

    def test_texto_limpio_sin_hallazgos(self):
        self.assertEqual(NoSecretsGuard().check("informe normal sin datos sensibles"), [])

    def test_patrones_extra(self):
        g = NoSecretsGuard(extra_patterns=[r"(?i)token_interno\s*=\s*\S+"])
        h = g.check("config: token_interno=abc123xyz")
        self.assertTrue(any("patron prohibido" in x.detalle for x in h))
        self.assertTrue(all(x.severidad == "critica" for x in h))


class TestMaxLengthGuard(unittest.TestCase):
    def test_exceso(self):
        g = MaxLengthGuard(max_chars=10)
        h = g.check("x" * 11)
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0].severidad, "alta")
        self.assertEqual(g.check("corto"), [])


class TestJsonSchemaGuard(unittest.TestCase):
    def test_valido_e_invalido(self):
        g = JsonSchemaGuard(SCHEMAS["task"])
        self.assertEqual(g.check('{"task_id":"t","kind":"k","instruction":"i"}'), [])
        h = g.check('{"task_id":"t"}')
        self.assertEqual(len(h), 1)
        self.assertIn("kind", h[0].detalle)
        h2 = g.check("no es json")
        self.assertEqual(len(h2), 1)

    def test_acepta_objeto_directo(self):
        g = JsonSchemaGuard(SCHEMAS["budget"])
        self.assertEqual(g.check("", {"total": 10}), [])


class TestRequiredKeysGuard(unittest.TestCase):
    def test_faltan_claves(self):
        g = RequiredKeysGuard(["repo", "secrets"])
        h = g.check("", {"repo": "x"})
        self.assertEqual(len(h), 1)
        self.assertIn("secrets", h[0].detalle)
        self.assertEqual(g.check("", {"repo": "x", "secrets": []}), [])
        h2 = g.check("texto plano", None)  # no es dict
        self.assertEqual(len(h2), 1)


class TestForbiddenPatternsGuard(unittest.TestCase):
    def test_prohibido(self):
        g = ForbiddenPatternsGuard([r"(?i)TODO\s*:", r"FIXME"])
        h = g.check("FIXME arreglar esto")
        self.assertEqual(len(h), 1)
        self.assertEqual(g.check("todo ok"), [])


class TestPipeline(unittest.TestCase):
    def test_compone_y_agrega(self):
        p = GuardPipeline([MaxLengthGuard(5), ForbiddenPatternsGuard([r"malo"])])
        h = p.check("texto malo y largo")
        self.assertEqual(len(h), 2)
        self.assertEqual(p.names(), ["longitud_max", "patrones_prohibidos"])

    def test_guard_roto_no_tumba(self):
        class Roto:
            name = "roto"

            def check(self, texto, artifact=None):
                raise RuntimeError("boom")

        p = GuardPipeline([Roto(), MaxLengthGuard(100)])
        h = p.check("ok")
        self.assertEqual(len(h), 1)
        self.assertEqual(h[0].herramienta, "roto")
        self.assertIn("roto", h[0].detalle)

    def test_default_pipeline(self):
        p = default_pipeline()
        self.assertEqual(p.names(), ["no_secretos", "longitud_max"])
        h = p.check("mail: a@b.co")
        self.assertTrue(h)


if __name__ == "__main__":
    unittest.main()
