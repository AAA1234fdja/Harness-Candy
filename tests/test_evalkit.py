"""Tests del golden set: casos dorados, reporte y puerta (gate) de CI."""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from helpers import make_pool, make_repo

from harness_candy.agents import SecurityScanAgent, ScriptedBackend
from harness_candy.components import WEV
from harness_candy.evalkit import GoldenSet, load_golden, run_golden
from harness_candy.harness import Budget, HarnessStore
from harness_candy.schemas import SchemaError
from harness_candy.security import SecurityGate


def golden_dict(root, q_min=0.9):
    return {
        "name": "security-scan-basico",
        "min_pass_rate": 0.5,
        "cases": [
            {
                "id": "repo-limpio",
                "task": {
                    "task_id": "scan-1",
                    "kind": "security_scan",
                    "instruction": "escanear",
                    "inputs": {"root": str(root)},
                    "criterios": [{"id": "informe_json_valido", "peso": 3.0}, {"id": "compile_ok", "peso": 2.0}],
                },
                "expect": {
                    "veredicto": "aprobado",
                    "q_min": q_min,
                    "artifact_json_keys": ["files_scanned", "secrets", "compile_errors"],
                },
            },
            {
                "id": "imposible",
                "task": {
                    "task_id": "scan-2",
                    "kind": "security_scan",
                    "instruction": "escanear",
                    "inputs": {"root": str(root)},
                    "criterios": [{"id": "informe_json_valido", "peso": 1.0}],
                },
                "expect": {"q_min": 1.01 if False else 0.999999, "artifact_contains": ["NO_EXISTE_ESTE_TEXTO"]},
            },
        ],
    }


class TestGoldenSet(unittest.TestCase):
    def test_from_dict_valida(self):
        g = GoldenSet.from_dict(golden_dict("/tmp"))
        self.assertEqual(len(g.cases), 2)
        self.assertEqual(g.min_pass_rate, 0.5)

    def test_esquema_rechaza(self):
        with self.assertRaises(SchemaError):
            GoldenSet.from_dict({"name": "x", "cases": [{"id": "c"}]})  # faltan task/expect

    def test_load_golden_archivo(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "g.json"
            p.write_text(json.dumps(golden_dict(td)), encoding="utf-8")
            g = load_golden(p)
            self.assertEqual(g.name, "security-scan-basico")


class TestRunGolden(unittest.TestCase):
    def _agent(self):
        return SecurityScanAgent("XEV", "modelo-ligero", ScriptedBackend(lambda *a, **k: "ok"))

    def test_reporte_con_pasados_y_fallidos(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td, with_secret=False)
            g = GoldenSet.from_dict(golden_dict(root, q_min=0.5))
            report = run_golden(
                g, agent=self._agent(), pool=make_pool(), store=HarnessStore(),
                budget=Budget(total=100_000, beta=0.5, k=2, m=3), wev=WEV(SecurityGate()),
                trace_dir=Path(td) / "traces", seed=0,
            )
            self.assertEqual(report.total, 2)
            self.assertEqual(report.passed, 1)   # repo-limpio pasa
            self.assertEqual(report.failed, 1)    # imposible falla (texto que no existe)
            self.assertAlmostEqual(report.pass_rate, 0.5)
            d = report.to_dict()
            self.assertTrue(d["gate_ok"])         # pass_rate 0.5 >= min_pass_rate 0.5
            caso_fail = [r for r in report.results if not r.passed][0]
            self.assertEqual(caso_fail.case_id, "imposible")
            self.assertTrue(any("NO_EXISTE_ESTE_TEXTO" in r for r in caso_fail.reasons))

    def test_gate_ok_cuando_supera_umbral(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td, with_secret=False)
            data = golden_dict(root, q_min=0.5)
            data["min_pass_rate"] = 0.5
            data["cases"] = data["cases"][:1]  # solo el que pasa
            g = GoldenSet.from_dict(data)
            report = run_golden(
                g, agent=self._agent(), pool=make_pool(), store=HarnessStore(),
                budget=Budget(total=100_000, beta=0.5, k=2, m=3), wev=WEV(SecurityGate()),
                trace_dir=Path(td) / "traces",
            )
            self.assertEqual(report.pass_rate, 1.0)
            self.assertTrue(report.to_dict()["gate_ok"])
            report.assert_gate()  # no lanza

    def test_assert_gate_lanza_si_no_alcanza(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td, with_secret=False)
            g = GoldenSet.from_dict(golden_dict(root))
            report = run_golden(
                g, agent=self._agent(), pool=make_pool(), store=HarnessStore(),
                budget=Budget(total=100_000, beta=0.5, k=2, m=3), wev=WEV(SecurityGate()),
                trace_dir=Path(td) / "traces",
            )
            with self.assertRaises(AssertionError) as ctx:
                report.assert_gate(min_pass_rate=0.99)
            self.assertIn("imposible", str(ctx.exception))

    def test_max_cases(self):
        with tempfile.TemporaryDirectory() as td:
            root = make_repo(td, with_secret=False)
            g = GoldenSet.from_dict(golden_dict(root))
            report = run_golden(
                g, agent=self._agent(), pool=make_pool(), store=HarnessStore(),
                budget=Budget(total=100_000, beta=0.5, k=2, m=3), wev=WEV(SecurityGate()),
                trace_dir=Path(td) / "traces", max_cases=1,
            )
            self.assertEqual(report.total, 1)


if __name__ == "__main__":
    unittest.main()
