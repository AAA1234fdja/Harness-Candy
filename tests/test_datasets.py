"""Tests de datasets JSONL de evaluacion y comparacion A/B."""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from helpers import make_pool, make_repo

from harness_candy.agents import SecurityScanAgent, ScriptedBackend
from harness_candy.components import WEV
from harness_candy.datasets import compare_reports, load_dataset, run_dataset
from harness_candy.evalkit import EvalReport, CaseResult
from harness_candy.harness import Budget, HarnessStore
from harness_candy.security import SecurityGate


def escribir_dataset(td, root):
    lineas = [
        {"id": "c1", "task": {"task_id": "s1", "kind": "security_scan", "instruction": "i",
                              "inputs": {"root": str(root)},
                              "criterios": [{"id": "informe_json_valido", "peso": 3.0}]},
         "expect": {"veredicto": "aprobado"}},
        {"id": "c2", "task": {"task_id": "s2", "kind": "security_scan", "instruction": "i",
                              "inputs": {"root": str(root)},
                              "criterios": [{"id": "informe_json_valido", "peso": 3.0}]},
         "expect": {"artifact_contains": ["NO_EXISTE"]}},
    ]
    p = Path(td) / "ds.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lineas) + "\n", encoding="utf-8")
    return p


class TestLoadDataset(unittest.TestCase):
    def test_carga_jsonl(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td)
            p = escribir_dataset(td, root)
            ds = load_dataset(p)
            self.assertEqual(ds.name, "ds")
            self.assertEqual(len(ds.cases), 2)
            self.assertEqual(ds.cases[0].id, "c1")

    def test_dataset_vacio_error(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "vacio.jsonl"
            p.write_text("\n\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_dataset(p)

    def test_linea_mala_rechazada(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "mala.jsonl"
            p.write_text(json.dumps({"id": "x"}) + "\n", encoding="utf-8")  # sin task/expect
            with self.assertRaises(Exception):
                load_dataset(p)


class TestRunDataset(unittest.TestCase):
    def test_run_dataset(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td, with_secret=False)
            p = escribir_dataset(td, root)
            report = run_dataset(
                p, agent=SecurityScanAgent("XEV", "m", ScriptedBackend(lambda *a, **k: "ok")),
                pool=make_pool(), store=HarnessStore(),
                budget=Budget(total=100_000, beta=0.5, k=2, m=3), wev=WEV(SecurityGate()),
                trace_dir=Path(td) / "tr",
            )
            self.assertEqual(report.total, 2)
            self.assertEqual(report.passed, 1)  # c2 falla (texto inexistente)


class TestCompareReports(unittest.TestCase):
    def test_comparacion(self):
        a = EvalReport("A", 4, 3, [CaseResult("c1", True, 1.0, "aprobado"), CaseResult("c2", True, 1.0, "aprobado"),
                                    CaseResult("c3", True, 1.0, "aprobado"), CaseResult("c4", False, 0.1, "rechazado")], 0.0)
        b = EvalReport("B", 4, 2, [CaseResult("c1", True, 1.0, "aprobado"), CaseResult("c2", False, 0.1, "rechazado"),
                                    CaseResult("c3", True, 1.0, "aprobado"), CaseResult("c4", True, 0.9, "aprobado")], 0.0)
        c = compare_reports(a, b)
        self.assertAlmostEqual(c.pass_rate_a, 0.75)
        self.assertAlmostEqual(c.pass_rate_b, 0.5)
        self.assertAlmostEqual(c.delta_pp, -25.0)
        self.assertFalse(c.to_dict()["b_mejor"])
        self.assertEqual(c.solo_en_a, ["c2"])
        self.assertEqual(c.solo_en_b, ["c4"])
        self.assertEqual(c.iguales, 2)


if __name__ == "__main__":
    unittest.main()
