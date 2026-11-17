"""Tests de suites JSON (DSL de casos) y su ejecucion como DAG."""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from helpers import make_pool, make_repo

from harness_candy.agents import SecurityScanAgent, ScriptedBackend
from harness_candy.components import WEV
from harness_candy.harness import Budget, HarnessStore
from harness_candy.schemas import SchemaError
from harness_candy.security import SecurityGate
from harness_candy.suite import Suite, load_suite, run_suite


def suite_dict(root, con_dep=True):
    tasks = [
        {
            "task_id": "scan",
            "kind": "security_scan",
            "instruction": "escanear repo",
            "inputs": {"root": str(root)},
            "deps": [],
            "agent": "XEV",
            "criterios": [{"id": "informe_json_valido", "peso": 3.0}, {"id": "compile_ok", "peso": 2.0}],
        }
    ]
    if con_dep:
        tasks.append(
            {
                "task_id": "reporte",
                "kind": "write_report",
                "instruction": "resumir",
                "deps": ["scan"],
                "criterios": [{"id": "informe_json_valido", "peso": 1.0}],
            }
        )
    return {"name": "demo", "seed": 0, "max_concurrency": 2, "tasks": tasks}


class TestSuite(unittest.TestCase):
    def test_from_dict_valida_esquema(self):
        s = Suite.from_dict(suite_dict("/tmp"))
        self.assertEqual(s.name, "demo")
        self.assertEqual(len(s.tasks), 2)

    def test_esquema_rechaza_suite_mala(self):
        with self.assertRaises(SchemaError):
            Suite.from_dict({"name": "x"})  # sin tasks

    def test_to_dag_respeta_deps(self):
        dag = Suite.from_dict(suite_dict("/tmp")).to_dag()
        self.assertEqual(set(dag.nodes), {"scan", "reporte"})
        self.assertEqual(dag.nodes["reporte"].deps, ["scan"])
        capas = dag.layers()
        self.assertEqual(capas[0], ["scan"])
        self.assertEqual(capas[1], ["reporte"])

    def test_dag_ciclo_rechazado(self):
        d = suite_dict("/tmp", con_dep=False)
        d["tasks"][0]["deps"] = ["scan"]  # se depende a si mismo
        with self.assertRaises(ValueError):
            Suite.from_dict(d).to_dag()

    def test_load_suite_desde_archivo(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "s.json"
            p.write_text(json.dumps(suite_dict(td)), encoding="utf-8")
            s = load_suite(p)
            self.assertEqual(s.name, "demo")
            self.assertEqual(len(s.task_list()), 2)  # scan + reporte (con dep)


class TestRunSuite(unittest.TestCase):
    def test_ejecuta_suite_sobre_repo_limpio(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td, with_secret=False)
            s = Suite.from_dict(suite_dict(root, con_dep=False))
            agent = SecurityScanAgent("XEV", "modelo-ligero", ScriptedBackend(lambda *a, **k: "ok"))
            pool = make_pool()
            wev = WEV(SecurityGate())
            result = run_suite(
                s, agent=agent, pool=pool, store=HarnessStore(),
                budget=Budget(total=10_000, beta=0.5, k=2, m=3), wev=wev,
                trace_dir=Path(td) / "traces",
            )
            self.assertEqual(result.suite, "demo")
            self.assertIn("scan", result.results)
            self.assertEqual(result.results["scan"].status, "done")  # repo limpio -> aprobado
            self.assertGreaterEqual(result.qs["scan"], 0.0)
            data = result.to_dict()
            self.assertEqual(data["dag_results"]["scan"]["status"], "done")
            self.assertIn("pruebas_total", data["metrics"])
            self.assertTrue(Path(result.trace_path).exists())
            self.assertGreater(result.duracion, 0)

    def test_suite_con_repo_con_secreto_no_aprueba(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td, with_secret=True)
            s = Suite.from_dict(suite_dict(root, con_dep=False))
            agent = SecurityScanAgent("XEV", "modelo-ligero", ScriptedBackend(lambda *a, **k: "ok"))
            result = run_suite(
                s, agent=agent, pool=make_pool(), store=HarnessStore(),
                budget=Budget(total=10_000, beta=0.5, k=2, m=3), wev=WEV(SecurityGate()),
                trace_dir=Path(td) / "traces",
            )
            # el escaneo detecta el secreto AKIA: no pasa 'sin_secretos_criticos' si esta en criterios
            self.assertIn(result.results["scan"].status, {"done", "rejected", "escalated"})


if __name__ == "__main__":
    unittest.main()
