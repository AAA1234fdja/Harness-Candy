"""Tests de construccion de contexto del executor y marcas de corrida (quinta ola)."""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from harness_candy.agents import Task
from harness_candy.context import ContextBundle, Fragmento, construir_contexto
from harness_candy.quality import Criterion
from harness_candy.runmark import (
    ENV_RELEVANTES,
    RunMark,
    crear_runmark,
    fingerprint_env,
    verificar_reproducibilidad,
)


def tarea():
    return Task("t-ctx", "security_scan", "escanear el repo", {"root": "."}, [Criterion("c1")])


class TestConstruirContexto(unittest.TestCase):
    def test_fragmentos_dict_y_orden_por_score(self):
        b = construir_contexto(
            tarea(),
            fragmentos=[
                {"contenido": "bajo", "procedencia": "b.md", "score": 0.1},
                {"contenido": "alto", "procedencia": "a.md", "score": 0.9},
            ],
            historial=["h1"],
        )
        self.assertIsInstance(b, ContextBundle)
        self.assertEqual(b.fragmentos[0].procedencia, "a.md")
        self.assertEqual(b.historial, ["h1"])

    def test_recorte_por_max_tokens(self):
        grande = "palabra " * 2000
        b = construir_contexto(
            tarea(),
            fragmentos=[
                {"contenido": "chico", "procedencia": "c.md", "score": 0.9},
                {"contenido": grande, "procedencia": "g.md", "score": 0.1},
            ],
            max_tokens=50,
        )
        # el fragmento chico entra; el grande se recorta o se excluye segun presupuesto
        self.assertEqual(b.fragmentos[0].procedencia, "c.md")
        self.assertLessEqual(len(b.fragmentos), 2)
        self.assertGreater(b.sobrante_tokens, 0)

    def test_fragmentos_objeto_fragmento(self):
        b = construir_contexto(tarea(), fragmentos=[Fragmento("txt", "f.md", 0.5)])
        self.assertEqual(b.fragmentos[0].contenido, "txt")

    def test_to_prompt_y_to_dict(self):
        b = construir_contexto(tarea(), fragmentos=[{"contenido": "doc", "procedencia": "d.md", "score": 1.0}], historial=["x"])
        prompt = b.to_prompt()
        self.assertIn("escanear el repo", prompt)
        self.assertIn("d.md", prompt)
        self.assertIn("x", prompt)
        d = b.to_dict()
        json.dumps(d)
        self.assertEqual(d["task_id"], "t-ctx")
        self.assertEqual(d["fragmentos"][0]["procedencia"], "d.md")

    def test_sin_fragmentos(self):
        b = construir_contexto(tarea())
        self.assertEqual(b.fragmentos, [])
        self.assertIn("escanear el repo", b.to_prompt())


class TestRunMark(unittest.TestCase):
    def test_fingerprint_solo_nombres(self):
        fp = fingerprint_env({"XKIRO_API_KEY": "sk-valor-secreto", "HOME": "/root", "OTRA": "x"})
        self.assertIn("XKIRO_API_KEY", fp)
        self.assertNotIn("HOME", fp)
        self.assertNotIn("OTRA", fp)
        for v in fp:
            self.assertIn(v, ENV_RELEVANTES)

    def test_crear_runmark_en_repo(self):
        with tempfile.TemporaryDirectory() as td:
            m = crear_runmark("run-x", seed=7, params={"k": 2}, root=td, environ={"XKIRO_API_KEY": "sk-abc"})
            self.assertEqual(m.run_id, "run-x")
            self.assertEqual(m.seed, 7)
            self.assertEqual(m.params, {"k": 2})
            self.assertIn("XKIRO_API_KEY", m.env_presentes)
            self.assertNotIn("sk-abc", json.dumps(m.to_dict()))  # jamas el valor
            # en un dir sin git: commit unknown pero no falla
            self.assertEqual(m.git_commit, "unknown")

    def test_crear_runmark_con_git_y_archivos(self):
        repo = Path(__file__).resolve().parents[1]
        m = crear_runmark("run-git", seed=1, root=repo, archivos=["pyproject.toml"], environ={})
        self.assertNotEqual(m.git_commit, "unknown")
        self.assertEqual(len(m.git_commit), 40)
        self.assertIn("pyproject.toml", m.archivos)
        self.assertEqual(len(m.archivos["pyproject.toml"]), 64)  # sha256 hex

    def test_verificar_reproducibilidad(self):
        with tempfile.TemporaryDirectory() as td:
            a = crear_runmark("a", seed=1, params={"k": 1}, root=td, environ={"XKIRO_API_KEY": "sk-1"})
            b = crear_runmark("b", seed=1, params={"k": 1}, root=td, environ={"XKIRO_API_KEY": "sk-otra"})
            v = verificar_reproducibilidad(a, b)
            self.assertTrue(v["iguales"])  # mismos params/seed/env-nombres => reproducible
            c = crear_runmark("c", seed=2, params={"k": 1}, root=td, environ={})
            v2 = verificar_reproducibilidad(a, c)
            self.assertFalse(v2["iguales"])
            self.assertTrue(any("seed" in d for d in v2["diferencias"]))

    def test_save_load(self):
        with tempfile.TemporaryDirectory() as td:
            m = crear_runmark("run-s", seed=3, params={"m": 2}, root=td, environ={})
            p = Path(td) / "mark.json"
            m.save(p)
            m2 = RunMark.load(p)
            self.assertEqual(m2.run_id, "run-s")
            self.assertEqual(m2.seed, 3)
            json.dumps(m2.to_dict())


if __name__ == "__main__":
    unittest.main()
