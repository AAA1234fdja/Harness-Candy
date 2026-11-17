import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.memory import KnowledgeMemory, VariableMemory
from harness_candy.pool import LIGHT_TAG, POWER_TAG, ModelPool, PoolEntry


class TestVariableMemory(unittest.TestCase):
    def test_versiones_y_ambitos(self):
        mem = VariableMemory()
        v1 = mem.set("estado", "ini", actor="XEV")
        v2 = mem.set("estado", "fin", actor="XEV")
        self.assertEqual((v1, v2), (1, 2))
        self.assertEqual(mem.get("estado"), "fin")
        mem.set("proyecto", 1, scope="project", actor="ISA")
        self.assertEqual(mem.get("proyecto", scope="project"), 1)
        self.assertEqual(len(mem.history("estado")), 2)

    def test_ambito_invalido(self):
        mem = VariableMemory()
        with self.assertRaises(ValueError):
            mem.set("x", 1, scope="invalido")

    def test_permisos(self):
        mem = VariableMemory()
        mem.set_write_permission("app:", {"ISA"})
        with self.assertRaises(PermissionError):
            mem.set("clave", 1, scope="app", actor="XEV")
        mem.set("clave", 1, scope="app", actor="ISA")  # ok

    def test_conflicto_write_write(self):
        mem = VariableMemory()
        mem.set("dato", "a", scope="project", actor="XEV")
        mem.set("dato", "b", scope="project", actor="ZEV")
        self.assertEqual(len(mem.conflicts), 1)


class TestKnowledgeMemory(unittest.TestCase):
    def test_remember_recall_procedencia(self):
        mem = KnowledgeMemory()
        e = mem.remember(
            "El repo usa MIT y Python 3.11; el harness por defecto debe incluir json_strict",
            fuente="docs", task_id="t1", autor="ZEV", nivel_confianza=0.9, tags=["arquitectura"],
        )
        self.assertIn("fuente", e.procedencia)
        results = mem.recall("harness json_strict del repo")
        self.assertTrue(any("json_strict" in r.content for r in results))

    def test_persistencia(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "kn.json"
            m1 = KnowledgeMemory(p)
            m1.remember("leccion: siempre validar mensajes", fuente="WEV", task_id="t9")
            m2 = KnowledgeMemory(p)
            self.assertEqual(len(m2.all()), 1)
            self.assertIn("validar", m2.all()[0].content)


class TestModelPool(unittest.TestCase):
    def make_pool(self):
        pool = ModelPool()
        pool.add(PoolEntry("flash-1", "gemini-flash", "GOOGLE_KEY_1", cost_per_1k=0.0001, roles={"xev", "zev"}, tag=LIGHT_TAG))
        pool.add(PoolEntry("flash-2", "gemini-flash", "GOOGLE_KEY_2", cost_per_1k=0.0001, roles={"xev", "zev"}, tag=LIGHT_TAG))
        pool.add(PoolEntry("opus-1", "claude-opus", "ANTHROPIC_KEY", cost_per_1k=0.015, roles={"isa", "ely"}, tag=POWER_TAG))
        return pool

    def test_seleccion_por_rol(self):
        pool = self.make_pool()
        clave, modelo = pool.select("security_scan")  # -> xev -> ligero
        self.assertIn("flash", clave)
        clave, modelo = pool.select("plan")  # -> isa -> potente
        self.assertEqual(clave, "opus-1")

    def test_rotacion_round_robin(self):
        pool = self.make_pool()
        a = pool.select("security_scan")
        b = pool.select("security_scan")
        self.assertNotEqual(a[0], b[0])  # rota entre flash-1 y flash-2

    def test_cuota(self):
        pool = self.make_pool()
        e = pool.entries()[0]
        e.quota_remaining = 0
        # sin cuota en flash-1, debe elegir otro elegible
        clave, _ = pool.select("security_scan")
        self.assertEqual(clave, "flash-2")

    def test_costo(self):
        pool = self.make_pool()
        self.assertAlmostEqual(pool.charge("opus-1", 2000), 0.03)


if __name__ == "__main__":
    unittest.main()
