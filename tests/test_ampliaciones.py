"""Tests de las ampliaciones del lote 5: herencia de plantillas, rerank RAG,
clases en codeedit, depends_on/foreach en workflow."""
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from helpers import make_pool, make_repo
from harness_candy.agents import ScriptedBackend, SecurityScanAgent
from harness_candy.codeedit import add_class, add_decorator, list_functions, remove_function
from harness_candy.components import WEV
from harness_candy.harness import Harness, HarnessStore
from harness_candy.rag import RAGPipeline, cobertura_terminos, expand_query, rerank_por_cobertura
from harness_candy.security import SecurityGate
from harness_candy.templates import TemplateError, render_string
from harness_candy.workflow import Workflow, run_workflow


class TestTemplatesHerencia(unittest.TestCase):
    def test_extends_block(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "base.txt").write_text("INI [{% block cuerpo %}defecto{% endblock %}] FIN")
            hija = '{% extends "base.txt" %}{% block cuerpo %}Hola {{ nombre }}{% endblock %}'
            self.assertEqual(render_string(hija, base_dir=td, nombre="Ada"), "INI [Hola Ada] FIN")

    def test_extends_sin_bloque_usa_defecto(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "base.txt").write_text("[{% block c %}defecto{% endblock %}]")
            hija = '{% extends "base.txt" %}'
            self.assertEqual(render_string(hija, base_dir=td), "[defecto]")

    def test_include(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "p.txt").write_text("<{{ x }}>")
            main = 'A {% include "p.txt" %} B'
            self.assertEqual(render_string(main, base_dir=td, x=1), "A <1> B")

    def test_include_ciclico_rechazado(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.txt").write_text('{% include "b.txt" %}')
            (Path(td) / "b.txt").write_text('{% include "a.txt" %}')
            with self.assertRaises(TemplateError):
                render_string((Path(td) / "a.txt").read_text(), base_dir=td)

    def test_include_fuera_de_base_rechazado(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(TemplateError):
                render_string('{% include "../fuera.txt" %}', base_dir=td)


class TestRagAmpliado(unittest.TestCase):
    def test_cobertura(self):
        self.assertGreater(cobertura_terminos("claves api", "las claves api van en entorno"), 0.9)
        self.assertEqual(cobertura_terminos("", "x"), 0.0)

    def test_rerank(self):
        res = [
            {"score": 0.9, "contenido": "aaa bbb", "procedencia": "x", "indice": 0},
            {"score": 0.1, "contenido": "claves api entorno", "procedencia": "y", "indice": 1},
        ]
        out = rerank_por_cobertura("claves api", res)
        self.assertEqual(out[0]["procedencia"], "y")
        self.assertIn("score_final", out[0])

    def test_expand_query(self):
        pipe = RAGPipeline(chunk_size=100, chunk_overlap=20)
        pipe.add_text("a.md", "zebra tigre leon pantera felinos salvajes de la selva africana")
        q = expand_query("zebra", pipe.bm25, max_extra=2)
        self.assertTrue(q.startswith("zebra"))
        self.assertGreater(len(q), len("zebra"))

    def test_query_con_rerank_y_expand(self):
        pipe = RAGPipeline(chunk_size=200, chunk_overlap=40)
        pipe.add_text("a.md", "Las claves API solo viven en variables de entorno. Nunca en el codigo.")
        pipe.add_text("b.md", "El DAG ejecuta tareas en paralelo con concurrencia limitada.")
        r = pipe.query("claves API entorno", k=2, rerank=True, expand=True)
        self.assertEqual(r["fragmentos"][0]["procedencia"], "a.md")


class TestCodeeditAmpliado(unittest.TestCase):
    def test_add_class(self):
        import ast

        out = add_class(
            "def f():\n    return 1\n",
            "Repo",
            methods=[{"name": "get", "args": ["self", "k"], "body": "return self.datos.get(k)"}],
            bases=["object"],
            docstring="Repo demo",
        )
        ast.parse(out)
        self.assertIn("class Repo(object):", out)
        self.assertIn("def get(self, k):", out)

    def test_remove_function_y_list(self):
        src = "def f():\n    return 1\ndef g():\n    return 2\n"
        self.assertEqual(list_functions(src), ["f", "g"])
        out = remove_function(src, "g")
        self.assertEqual(list_functions(out), ["f"])

    def test_add_decorator(self):
        out = add_decorator("def f():\n    return 1\n", "f", "staticmethod")
        self.assertIn("@staticmethod", out)


class TestWorkflowAmpliado(unittest.TestCase):
    def _entorno(self, td):
        pool = make_pool()
        store = HarnessStore()
        store.save("security_scan", "modelo-ligero", Harness(), evidence={"q": [1.0]}, q_mean=1.0)
        wev = WEV(SecurityGate())
        agent = SecurityScanAgent("XEV", "modelo-ligero", ScriptedBackend(lambda *a, **k: "ok"))
        return pool, store, wev, agent

    def test_depends_on_ordena(self):
        with tempfile.TemporaryDirectory() as td:
            pool, store, wev, agent = self._entorno(td)
            wf = Workflow.from_dict({"name": "w", "steps": [
                {"id": "b", "type": "set", "key": "orden", "value": "expr:ctx.get('orden','') + 'b'", "depends_on": ["a"]},
                {"id": "a", "type": "set", "key": "orden", "value": "a"},
            ]})
            res = run_workflow(wf, agent=agent, pool=pool, store=store, wev=wev, trace_dir=Path(td) / "t", seed=0)
            self.assertEqual(res.context["orden"], "ab")

    def test_depends_on_ciclo_falla(self):
        with tempfile.TemporaryDirectory() as td:
            pool, store, wev, agent = self._entorno(td)
            wf = Workflow.from_dict({"name": "w", "steps": [
                {"id": "a", "type": "set", "key": "x", "value": 1, "depends_on": ["b"]},
                {"id": "b", "type": "set", "key": "y", "value": 2, "depends_on": ["a"]},
            ]})
            with self.assertRaises(ValueError):
                run_workflow(wf, agent=agent, pool=pool, store=store, wev=wev, trace_dir=Path(td) / "t", seed=0)

    def test_dep_desconocida_falla(self):
        with tempfile.TemporaryDirectory() as td:
            pool, store, wev, agent = self._entorno(td)
            wf = Workflow.from_dict({"name": "w", "steps": [{"id": "a", "type": "set", "key": "x", "value": 1, "depends_on": ["zz"]}]})
            with self.assertRaises(ValueError):
                run_workflow(wf, agent=agent, pool=pool, store=store, wev=wev, trace_dir=Path(td) / "t", seed=0)

    def test_foreach(self):
        with tempfile.TemporaryDirectory() as td:
            pool, store, wev, agent = self._entorno(td)
            wf = Workflow.from_dict({"name": "w", "context": {"nums": [1, 2, 3, 4]}, "steps": [
                {"id": "loop", "type": "foreach", "items": "ctx['nums']", "as": "n", "steps": [
                    {"id": "sumar", "type": "set", "key": "total", "value": "expr:ctx.get('total', 0) + ctx['n']"},
                ]},
            ]})
            res = run_workflow(wf, agent=agent, pool=pool, store=store, wev=wev, trace_dir=Path(td) / "t", seed=0)
            self.assertEqual(res.steps["loop"].status, "done")
            self.assertEqual(res.context["total"], 10)

    def test_foreach_items_no_lista_falla(self):
        with tempfile.TemporaryDirectory() as td:
            pool, store, wev, agent = self._entorno(td)
            wf = Workflow.from_dict({"name": "w", "context": {"nums": 5}, "steps": [
                {"id": "loop", "type": "foreach", "items": "ctx['nums']", "steps": [{"id": "s", "type": "set", "key": "x", "value": 1}]},
            ]})
            res = run_workflow(wf, agent=agent, pool=pool, store=store, wev=wev, trace_dir=Path(td) / "t", seed=0)
            self.assertEqual(res.steps["loop"].status, "failed")

    def test_foreach_requiere_campos(self):
        with self.assertRaises(ValueError):
            Workflow.from_dict({"name": "w", "steps": [{"id": "l", "type": "foreach"}]})


if __name__ == "__main__":
    unittest.main()
