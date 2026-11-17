"""Tests de la suite de evaluacion agregada (evalsuite.py)."""
import json
import tempfile
import unittest
from pathlib import Path

import _path  # noqa: F401
from helpers import make_pool, make_repo
from harness_candy.agents import ScriptedBackend, SecurityScanAgent
from harness_candy.components import WEV
from harness_candy.evalsuite import EvalSuiteResult, _bootstrap_pass_rate, html_eval_report, run_eval_suite, significancia_vs
from harness_candy.harness import Harness, HarnessStore
from harness_candy.security import SecurityGate


def _golden(td, repo):
    data = {
        "name": "mini-golden",
        "min_pass_rate": 0.5,
        "cases": [
            {
                "id": "scan-limpio",
                "task": {
                    "task_id": "g1",
                    "kind": "security_scan",
                    "instruction": "Escanear el repo demo",
                    "inputs": {"root": str(repo)},
                    "criterios": [
                        {"id": "informe_json_valido", "peso": 3.0},
                        {"id": "compile_ok", "peso": 2.0},
                        {"id": "sin_secretos_criticos", "peso": 3.0},
                    ],
                },
                "expect": {"veredicto": "aprobado", "q_min": 0.9},
            }
        ],
    }
    p = Path(td) / "golden.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


class TestEvalSuite(unittest.TestCase):
    def test_bootstrap_pass_rate(self):
        b = _bootstrap_pass_rate([True] * 8 + [False] * 2, n_boot=500, seed=0)
        self.assertLessEqual(b["p2_5"], b["p50"])
        self.assertLessEqual(b["p50"], b["p97_5"])
        self.assertGreater(b["p97_5"], 0.5)
        self.assertEqual(_bootstrap_pass_rate([]), {"p2_5": 0.0, "p50": 0.0, "p97_5": 0.0})

    def test_run_eval_suite(self):
        with tempfile.TemporaryDirectory() as td:
            repo = make_repo(td)
            gpath = _golden(td, repo)
            pool = make_pool()
            store = HarnessStore()
            store.save("security_scan", "modelo-ligero", Harness(), evidence={"q": [1.0]}, q_mean=1.0)
            wev = WEV(SecurityGate())
            agent = SecurityScanAgent("XEV", "modelo-ligero", ScriptedBackend(lambda *a, **k: "ok"))
            res = run_eval_suite(gpath, agent=agent, pool=pool, store=store, wev=wev, seeds=(0, 1), trace_dir=Path(td) / "traces", n_boot=200)
            self.assertIsInstance(res, EvalSuiteResult)
            self.assertEqual(res.n_casos, 2)  # 1 caso x 2 semillas
            self.assertEqual(set(res.pass_rate_por_seed), {0, 1})
            self.assertGreaterEqual(res.pass_rate_global, 0.0)
            self.assertLessEqual(res.pass_rate_global, 1.0)
            mc = res.matriz_confusion
            total = sum(sum(v.values()) for v in mc.values())
            self.assertEqual(total, 2)
            d = res.to_dict()
            self.assertIn("bootstrap", d)
            self.assertIn("pass_rate_global", d)

    def test_html_eval_report(self):
        res = EvalSuiteResult(
            golden="g", seeds=[0, 1], pass_rate_por_seed={0: 1.0, 1: 0.5}, pass_rate_global=0.75,
            matriz_confusion={"aprobado": {"aprobado": 1, "rechazado": 0}, "rechazado": {"aprobado": 1, "rechazado": 0}},
            bootstrap={"p2_5": 0.5, "p50": 0.75, "p97_5": 1.0}, n_casos=2,
        )
        h = html_eval_report(res, extra={"delta": 0.1})
        self.assertIn("<!doctype html>", h)
        self.assertIn("0.750", h)
        self.assertIn("Matriz de confusion", h)
        self.assertIn("delta", h)

    def test_significancia_vs(self):
        a = EvalSuiteResult("a", [0, 1], {0: 0.5, 1: 0.5}, 0.5, {"aprobado": {"aprobado": 1, "rechazado": 1}, "rechazado": {"aprobado": 0, "rechazado": 0}}, {"p2_5": 0.5, "p50": 0.5, "p97_5": 0.5}, 4)
        b = EvalSuiteResult("b", [0, 1], {0: 1.0, 1: 1.0}, 1.0, {"aprobado": {"aprobado": 2, "rechazado": 0}, "rechazado": {"aprobado": 0, "rechazado": 0}}, {"p2_5": 1.0, "p50": 1.0, "p97_5": 1.0}, 4)
        r = significancia_vs(a, b, n_boot=500, seed=1)
        self.assertIn("p_b_mejor_que_a", r)
        self.assertGreaterEqual(r["p_b_mejor_que_a"], 0.9)
        self.assertTrue(r["significativo_95"])
        self.assertEqual(len(r["ic95_delta"]), 2)


if __name__ == "__main__":
    unittest.main()
